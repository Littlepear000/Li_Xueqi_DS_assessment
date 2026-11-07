"""Portfolio-level pattern workflows (replication & scaling).

Unlike the approach workflows under ``piaa/workflows/`` (one run per project),
a pattern workflow reads the *whole* review database at once and asks which
approaches recur across projects. Each version is a folder next to this file
with the same layout as an approach workflow::

    piaa/patterns/r1/
        config.yaml     parameters, step list and steps_meta (for the flowchart)
        steps.py        ``run(ctx)`` plus one ``step_<name>(ctx)`` per step
        prompts/*.md    prompt templates (optional LLM steps)
        workflow.html   human-readable methodology
        CHANGELOG.md

Results are written to ``<output_dir>/patterns/<stamp>_<version>[_label]/``:
``result.json`` (everything the web app shows), CSV tables and ``manifest.json``.

Usage from a notebook::

    from piaa.patterns import run_patterns
    manifest = run_patterns(db_path="output/pia_review.db", output_dir="output")
"""
from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from ..workflows import Workflow, _hash_folder

PATTERNS_ROOT = Path(__file__).parent


@dataclass
class PatternWorkflow(Workflow):
    """A pattern workflow version (same structure as an approach workflow)."""

    def module(self):
        return importlib.import_module(f"piaa.patterns.{self.version}.steps")


def load_pattern_workflow(version: str) -> PatternWorkflow:
    path = PATTERNS_ROOT / version
    cfg_path = path / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"pattern workflow '{version}' not found under {PATTERNS_ROOT}")
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    prompts = {p.stem: p.read_text(encoding="utf-8") for p in sorted((path / "prompts").glob("*.md"))}
    return PatternWorkflow(version=version, path=path, config=config, prompts=prompts, hash=_hash_folder(path))


def list_pattern_workflows() -> list[PatternWorkflow]:
    return [load_pattern_workflow(p.name) for p in sorted(PATTERNS_ROOT.iterdir())
            if p.is_dir() and (p / "config.yaml").exists()]


# ----------------------------------------------------------------------------- run context
@dataclass
class PatternContext:
    db_path: Path
    out_dir: Path
    workflow: PatternWorkflow
    llm: object = None                        # optional piaa.llm.LLMClient (only for LLM steps)
    index: object = None                      # optional piaa.documents.DocumentIndex (for reading context around evidence)
    progress: Callable[[str], None] | None = None
    data: dict = field(default_factory=dict)  # step outputs
    trace: list[dict] = field(default_factory=list)

    def cfg(self, key: str, default=None):
        return self.workflow.config.get(key, default)

    def log(self, step: str, status: str = "ok", note: str = "", **extra) -> None:
        self.trace.append({"step": step, "status": status, "note": note, "at": _now(), **extra})
        if self.progress:
            self.progress(f"[{step}] {status} {note}".strip())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_patterns(db_path: str | Path, output_dir: str | Path, version: str | None = None, label: str = "",
                 llm=None, progress: Callable[[str], None] | None = None, documents_dirs: list | None = None, index=None) -> dict:
    """Run a pattern workflow over the whole database and return its manifest.

    ``llm``: a ``piaa.llm.LLMClient`` for the verification step (skipped when None).
    ``documents_dirs`` / ``index``: where the project documents live, so the verification step can read
    the pages around each approach's evidence (``Settings.documents_dirs`` in the notebook).
    """
    wfs = list_pattern_workflows()
    if not wfs:
        raise FileNotFoundError("no pattern workflow found")
    wf = load_pattern_workflow(version) if version else wfs[-1]
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")
    tag = re.sub(r"[^A-Za-z0-9.+_-]+", "-", wf.tag).replace("+", "-")
    out = Path(output_dir) / "patterns" / f"{stamp}_{tag}{'_' + slug if slug else ''}"
    out.mkdir(parents=True, exist_ok=True)
    if index is None and documents_dirs:
        from ..documents import build_index
        index = build_index([Path(d) for d in documents_dirs])
    ctx = PatternContext(db_path=Path(db_path), out_dir=out, workflow=wf, llm=llm, progress=progress, index=index)
    wf.module().run(ctx)
    from ..versioning import stamp as version_stamp
    manifest = {"run": out.name, **version_stamp(wf), "label": label, "created_at": _now(),
                "db": str(db_path), "kpis": ctx.data.get("result", {}).get("kpis", {}), "trace": ctx.trace,
                "llm_calls": len(getattr(llm, "calls", []) or [])}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def list_runs(output_dir: str | Path) -> list[dict]:
    root = Path(output_dir) / "patterns"
    runs = []
    if root.exists():
        for d in sorted(root.iterdir(), reverse=True):
            m = d / "manifest.json"
            if d.is_dir() and m.exists() and (d / "result.json").exists():
                try:
                    runs.append(json.loads(m.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    continue
    return runs


def load_result(output_dir: str | Path, run: str | None = None) -> dict | None:
    runs = list_runs(output_dir)
    if not runs:
        return None
    name = run or runs[0]["run"]
    p = Path(output_dir) / "patterns" / name / "result.json"
    if not p.exists():
        return None
    res = json.loads(p.read_text(encoding="utf-8"))
    res["run"] = name
    res["manifest"] = next((r for r in runs if r["run"] == name), {})
    return res
