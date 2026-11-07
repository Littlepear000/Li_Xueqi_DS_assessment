"""Run a workflow on one project or on many.

:func:`run_project` is the *single-record test API*: it returns a fully
populated :class:`ProjectRecord` and writes it to ``output_dir/cache/projects/``.
:func:`run_batch` loops over projects with reuse / refresh / missing modes.
Both are what the web app will call behind its "Run" buttons.
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from pathlib import Path
from typing import Callable, Iterable

from .catalog import Project, load_projects
from .config import Settings
from .documents import DocumentIndex, build_index
from .llm import LLMClient
from .models import ProjectRecord, fingerprint, now_iso
from .replication import PortfolioStore
from .workflows import Workflow, load_workflow
from .versioning import label_run, package_version
from .workflows.base import RunContext


class Pipeline:
    """Holds the expensive shared objects (catalog, document index, portfolio store)."""

    def __init__(self, settings: Settings, workflow: str | None = None):
        self.settings = settings
        self.projects: dict[str, Project] = load_projects(settings.projects_csv)
        self.index: DocumentIndex = build_index(settings.documents_dirs)
        self.workflow: Workflow = load_workflow(workflow or settings.workflow)
        self.store = PortfolioStore.load(settings.cache_dir / "portfolio_approaches.json")
        self.store.register_projects(self.projects)
        wf_llm = self.workflow.config.get("llm", {})
        # The workflow's model name (claude-...) only applies to the Anthropic provider; for DeepSeek / OpenAI-compatible
        # providers the model chosen on the Setup page is kept. A copy is used so the app's shared settings are not changed.
        if wf_llm.get("model") and settings.llm.provider == "anthropic" and settings.llm.model != wf_llm["model"]:
            import dataclasses
            settings = dataclasses.replace(settings, llm=dataclasses.replace(settings.llm, model=wf_llm["model"]))
            self.settings = settings
        self.llm = LLMClient(settings.llm)
        self._lock = threading.RLock()
        self.cancel = threading.Event()   # set by the web app's Stop button

    # ------------------------------------------------------------------
    def input_fingerprint(self, project: Project) -> str:
        docs = [(d.guid, d.path.stat().st_size) for d in self.index.for_project(project.project_id)]
        return fingerprint([project.raw, docs, self.workflow.hash])

    def cached(self, project_id: str) -> ProjectRecord | None:
        p = self.settings.cache_dir / "projects" / f"{project_id}.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return _record_from_dict(data)

    def _save(self, rec: ProjectRecord, llm: LLMClient) -> Path:
        folder = self.settings.cache_dir / "projects"
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{rec.project_id}.json"
        p.write_text(rec.to_json(), encoding="utf-8")
        if self.settings.debug:
            # raw LLM exchange for prompt debugging ("raw prompts & responses" in the app)
            calls = [c.to_dict(include_text=True) for c in llm.calls]
            (folder / f"{rec.project_id}.{rec.run_id}.llm.json").write_text(json.dumps(calls, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    # ------------------------------------------------------------------
    def _acquire_documents(self, project_id: str, rec) -> None:
        """Before extraction, complete this project's documents from the WBG API into
        output/supplement_documents (added to the in-memory index). Never raises."""
        from .models import StepTrace, now_iso
        t = StepTrace(step="acquire", started_at=now_iso())
        try:
            from .acquire import fetch_missing
            have = self.index.by_project.get(project_id, [])
            keys = {f"{d.doc_type}|{d.doc_date}" for d in have}
            dest = self.settings.output_dir / "supplement_documents"
            notes: list[str] = []
            new = fetch_missing(project_id, keys, dest, log=notes.append)
            if new:
                with self._lock:
                    self.index.by_project.setdefault(project_id, []).extend(new)
            t.ended_at = now_iso(); t.status = "ok"
            t.note = (f"{len(new)} document(s) fetched from the WBG API" if new
                      else "no missing documents fetched") + (f"; {len(have)} already local" if have else "")
            t.output["fetched"] = len(new)
        except Exception as e:  # noqa: BLE001 - acquisition must never break a run
            t.ended_at = now_iso(); t.status = "skipped"; t.note = f"document acquisition skipped ({type(e).__name__})"
        rec.trace.append(t)

    def run_project(self, project_id: str) -> ProjectRecord:
        if project_id not in self.projects:
            raise KeyError(f"{project_id} is not in projects.csv")
        project = self.projects[project_id]
        llm = LLMClient(self.settings.llm, cancel=self.cancel)  # one client per run: thread-safe call log
        rec = ProjectRecord(project_id=project_id, workflow=self.workflow.version, workflow_hash=self.workflow.hash,
                            run_id=uuid.uuid4().hex[:8], started_at=now_iso(), input_fingerprint=self.input_fingerprint(project),
                            workflow_tag=self.workflow.tag, package_version=package_version())
        from .scope import scope_reason
        in_scope = not scope_reason(self.workflow.config.get("scope"), project)
        if in_scope and getattr(self.settings, "acquire", False) and not self.cancel.is_set():
            self._acquire_documents(project_id, rec)
        with self._lock:
            self.store.drop_project(project_id)  # a re-run replaces the project's entries in the portfolio store
        ctx = RunContext(self.settings, self.workflow, project, self.index, llm, rec, self.store, lock=self._lock)
        try:
            self.workflow.module().run(ctx)
        except Exception as e:  # keep the partial record and the error, never crash a batch
            rec.error = f"{type(e).__name__}: {e}"
            rec.trace.append(_failed_trace(str(e)))
        rec.ended_at = now_iso()
        rec.llm_usage = llm.usage()
        if self.cancel.is_set():
            rec.error = "cancelled: run stopped by user"
            return rec   # partial result: not written to the cache, the previous result stays
        if not self.settings.debug:
            _compact_trace(rec)
        self._save(rec, llm)
        return rec


def _compact_trace(rec: ProjectRecord) -> None:
    """Drop bulky step output (raw model JSON, keyword snippets); keep status, note and small summaries."""
    keep = {"distinct_hits", "tier", "by_dimension", "innovative", "dropped", "selected", "reasoning", "explicit", "store_size", "usage",
            "skipped", "units", "candidate_units", "extracted", "accepted", "rejected", "expanded", "merged",
            "legal_condition", "with_innovation_cue", "reject_codes", "legal_evidence"}
    for t in rec.trace:
        t.output = {k: v for k, v in t.output.items() if k in keep}


def _failed_trace(msg: str):
    from .models import StepTrace
    return StepTrace(step="exception", started_at=now_iso(), ended_at=now_iso(), status="failed", note=msg[:500] + "\n" + traceback.format_exc()[-1500:])


def _record_from_dict(d: dict) -> ProjectRecord:
    from .models import Approach, Attribute, Evidence, ReplicationLink, StepTrace

    def attr(x):
        return Attribute(**x) if x else None

    rec = ProjectRecord(project_id=d["project_id"], workflow=d["workflow"], workflow_hash=d["workflow_hash"], run_id=d["run_id"],
                        started_at=d["started_at"], ended_at=d.get("ended_at", ""), input_fingerprint=d.get("input_fingerprint", ""),
                        innovation_tier=d.get("innovation_tier", ""), innovation_keyword_hits=d.get("innovation_keyword_hits", 0),
                        innovative=d.get("innovative", ""), documents_used=d.get("documents_used", []), error=d.get("error", ""))
    for a in d.get("approaches", []):
        rec.approaches.append(Approach(
            approach_id=a["approach_id"], project_id=a["project_id"], name=a["name"], description=a.get("description", ""),
            evidence=Evidence(**a["evidence"]), why_innovative=a.get("why_innovative", ""),
            category=attr(a.get("category")), category_solution=attr(a.get("category_solution")),
            sector=attr(a.get("sector")), theme=attr(a.get("theme")),
            replication=[ReplicationLink(**r) for r in a.get("replication", [])],
            extra_evidence=[Evidence(**e) for e in a.get("extra_evidence", [])], status=a.get("status", "generated"),
            adoption=attr(a.get("adoption")), innovation_basis=a.get("innovation_basis", ""), innovation_cues=a.get("innovation_cues", [])))
        rec.approaches[-1].replication_verdict = a.get("replication_verdict", "")
    rec.trace = [StepTrace(**t) for t in d.get("trace", [])]
    rec.aec_rows = d.get("aec_rows", [])
    rec.review_status = d.get("review_status", "")
    rec.exclusion_log = d.get("exclusion_log", [])
    rec.llm_usage = d.get("llm_usage", {})
    rec.workflow_tag = label_run(rec.workflow, rec.workflow_hash, d.get("workflow_tag", ""))
    rec.package_version = d.get("package_version", "")
    return rec


# ----------------------------------------------------------------------------
# Public functions
# ----------------------------------------------------------------------------
def run_project(project_id: str, settings: Settings, workflow: str | None = None, pipeline: Pipeline | None = None) -> ProjectRecord:
    """Single-record test API: run ``workflow`` on one project and return the record."""
    pipe = pipeline or Pipeline(settings, workflow)
    return pipe.run_project(project_id)


def run_batch(project_ids: Iterable[str] | None, settings: Settings, workflow: str | None = None, mode: str = "reuse",
              progress: Callable[[str, str, ProjectRecord | None], None] | None = None) -> dict[str, ProjectRecord]:
    """Run many projects.

    mode:
      ``reuse``   skip projects whose cached record has the same input fingerprint (CSV row + documents + workflow);
      ``missing`` run only projects with no cached record at all;
      ``refresh`` run everything.
    ``progress(project_id, status, record)`` is called after each project (status: reused | done | failed).
    """
    pipe = Pipeline(settings, workflow)
    ids = list(project_ids) if project_ids else list(pipe.projects)
    out: dict[str, ProjectRecord] = {}
    todo: list[str] = []
    for pid in ids:
        if pid not in pipe.projects:
            progress and progress(pid, "failed: not in projects.csv", None)
            continue
        cached = pipe.cached(pid)
        if cached and mode == "missing":
            out[pid] = cached
            progress and progress(pid, "reused", cached)
            continue
        if cached and mode == "reuse" and cached.input_fingerprint == pipe.input_fingerprint(pipe.projects[pid]) and not cached.error:
            out[pid] = cached
            progress and progress(pid, "reused", cached)
            continue
        todo.append(pid)
    workers = max(1, settings.workers if settings.llm.provider != "mock" else 1)
    if workers == 1:
        for pid in todo:
            rec = pipe.run_project(pid)
            out[pid] = rec
            progress and progress(pid, "failed" if rec.error else "done", rec)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(pipe.run_project, pid): pid for pid in todo}
            for f in as_completed(futs):
                rec = f.result()
                out[rec.project_id] = rec
                progress and progress(rec.project_id, "failed" if rec.error else "done", rec)
    return out
