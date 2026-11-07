"""FastAPI server for the PIA Review web app.

Run with ``piaa serve --raw-dir ... --out ...`` (or ``uvicorn piaa.webapp.server:app``
after setting the PIAA_RAW_DIR / PIAA_OUTPUT_DIR environment variables).

The front-end is a single static page (``static/index.html``) that talks to
the JSON API below. Workflow runs execute in a background thread; the page
polls ``/api/jobs/{id}`` for progress.
"""
from __future__ import annotations

import json
from datetime import datetime
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from ..catalog import load_projects, validate_projects_csv
from ..config import LLMSettings, Settings
from ..documents import build_index, read_text
from ..export import export as export_tables
from ..runner import Pipeline, _record_from_dict
from ..taxonomy import dai_pillars
from ..workflows import list_workflows, load_workflow
from ..patterns import list_pattern_workflows, list_runs as list_pattern_runs, load_pattern_workflow, load_result as load_pattern_result, run_patterns
from .db import DB

STATIC = Path(__file__).parent / "static"
from .. import __version__ as PIAA_VERSION
app = FastAPI(title="PIA Review", version=PIAA_VERSION)

APP_BUILD = PIAA_VERSION   # version this server process was started with; the page gets the on-disk version (index())
_state: dict = {"db": None, "settings": None, "jobs": {}, "cancel": {}}   # cancel: job_id -> threading.Event


# ----------------------------------------------------------------------------
# bootstrap
# ----------------------------------------------------------------------------
def configure(raw_dir: str, output_dir: str, provider: str = "anthropic", model: str | None = None, workflow: str = "v1",
              base_url: str | None = None, api_key: str | None = None, do_reindex: bool = True, saving: dict | None = None) -> DB:
    """Bind the app to a data folder and an LLM provider. The provider, model, endpoint and key entered on the
    Setup page are kept in the SQLite settings table (local file) so runs started from the page use them."""
    db = DB(Path(output_dir) / "pia_review.db")
    stored = db.get_settings()
    if api_key is None and stored.get(f"api_key.{provider}"):
        api_key = stored[f"api_key.{provider}"]   # key previously entered on the Setup page for this provider
    # Token-saving options from the Setup page (no prompt or workflow change). Cheaper step models are kept per provider.
    sv = {"warm_cache": stored.get("saving.warm_cache", "1") != "0",
          "reuse_answers": stored.get("saving.reuse_answers", "0") == "1",
          "step_models": _json_dict(stored.get(f"saving.step_models.{provider}", ""))}
    sv.update({k: v for k, v in (saving or {}).items() if v is not None})
    sv["step_models"] = {k: str(v).strip() for k, v in sv["step_models"].items() if str(v or "").strip()}
    llm = LLMSettings(provider=provider, model=model or None, base_url=base_url or None, api_key=api_key or None,
                      step_models=sv["step_models"], response_cache=sv["reuse_answers"], warm_cache=sv["warm_cache"])
    settings = Settings(raw_dir=raw_dir, output_dir=output_dir, workflow=workflow, llm=llm)
    db.set_settings({"saving.warm_cache": "1" if sv["warm_cache"] else "0", "saving.reuse_answers": "1" if sv["reuse_answers"] else "0",
                     f"saving.step_models.{provider}": json.dumps(sv["step_models"])})
    db.set_settings({"raw_dir": str(settings.raw_dir), "output_dir": str(settings.output_dir), "provider": provider,
                     "model": settings.llm.model, "base_url": settings.llm.base_url or "", "workflow": workflow,
                     f"api_key.{provider}": settings.llm.api_key or "", "api_key_set": bool(settings.llm.api_key)})
    _state.update(db=db, settings=settings)
    if do_reindex:
        reindex()
    return db


def _json_dict(text: str) -> dict:
    try:
        d = json.loads(text) if text else {}
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def stored_provider(output_dir: str) -> str:
    """Provider last chosen on the Setup page (kept in the SQLite settings table), if any."""
    try:
        return DB(Path(output_dir) / "pia_review.db").get_settings().get("provider", "")
    except Exception:
        return ""


def reindex() -> dict:
    s, db = _state["settings"], _state["db"]
    projects = load_projects(s.projects_csv)
    index = build_index(s.documents_dirs)
    return db.load_catalog(projects, index)


def _db() -> DB:
    if _state["db"] is None:
        raw, out = os.environ.get("PIAA_RAW_DIR"), os.environ.get("PIAA_OUTPUT_DIR")
        if not raw or not out:
            raise HTTPException(503, "server not configured: start with `piaa serve --raw-dir ... --out ...`")
        configure(raw, out, os.environ.get("PIAA_PROVIDER") or stored_provider(out) or "anthropic")
    return _state["db"]


# ----------------------------------------------------------------------------
# static
# ----------------------------------------------------------------------------
_NO_CACHE = {"Cache-Control": "no-store"}


@app.get("/", response_class=HTMLResponse)
def index():
    # The page learns the package version as it is ON DISK now (piaa/__init__.py), the server reports the version it
    # was started with (/api/version). They differ only when the code was updated and the server not restarted.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="/static/app.js"></script>',
                        f'<script>window.APP_BUILD = "{_disk_version()}";</script>\n<script src="/static/app.js"></script>', 1)
    return HTMLResponse(html, headers=_NO_CACHE)


def _disk_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (Path(__file__).resolve().parents[1] / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else PIAA_VERSION


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)   # no body: a JSON "{}" with 204 made uvicorn raise "Too much data for declared Content-Length"


@app.get("/static/{name}")
def static(name: str):
    p = STATIC / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers=_NO_CACHE)


# ----------------------------------------------------------------------------
# setup
# ----------------------------------------------------------------------------
class SetupIn(BaseModel):
    raw_dir: str | None = None
    output_dir: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    workflow: str | None = None
    warm_cache: bool | None = None       # token saving: first call of each system prompt alone, then parallel calls read the cache
    reuse_answers: bool | None = None    # token saving: reuse stored answers for identical requests
    codes_model: str | None = None       # token saving: cheaper model for the sector & theme step ("" = main model)
    merge_model: str | None = None       # token saving: cheaper model for the merge step ("" = main model)


@app.get("/api/version")
def get_version():
    """Package version and the newest approach workflow (highest vN folder) with its current tag."""
    wfs = sorted(list_workflows(), key=lambda w: int(w.version[1:]) if w.version[1:].isdigit() else -1)
    latest = wfs[-1] if wfs else None
    out = {"package": PIAA_VERSION, "workflow": latest.version if latest else "", "workflow_tag": latest.tag if latest else "", "build": APP_BUILD}
    try:   # data source + latest change, for the sidebar and the Database 'New' badge
        db, st = _db(), _state["settings"]
        with db.conn() as c:
            out["projects"] = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            out["last_run"] = c.execute("SELECT MAX(started_at) FROM runs").fetchone()[0]
            marks = [c.execute(q).fetchone()[0] or "" for q in ("SELECT MAX(COALESCE(ended_at, started_at)) FROM runs", "SELECT MAX(at) FROM field_history",
                     "SELECT MAX(updated_at) FROM review WHERE status NOT IN ('not run', 'no documents', 'out of scope')")]   # reindex touches only those
        out.update(db_marker=max(marks), output_dir=str(st.output_dir), db=str(db.path))
    except Exception:  # noqa: BLE001 - version must answer even when the DB is busy
        pass
    return out


def _db_last_change() -> str:
    with _db().conn() as c:
        a = c.execute("SELECT MAX(started_at) FROM runs").fetchone()[0] or ""
        b = c.execute("SELECT MAX(at) FROM field_history WHERE source='manual'").fetchone()[0] or ""
    return max(a, b)


class ExamplesIn(BaseModel):
    enabled: bool = True
    good: list[dict] = []
    bad: list[dict] = []


@app.get("/api/examples")
def api_examples():
    """Reviewer-curated good / bad approach examples (stored next to projects.csv)."""
    from .. import examples
    _db()
    return examples.load(_state["settings"].output_dir, legacy_dir=_state["settings"].raw_dir)


@app.post("/api/examples")
def api_examples_save(body: ExamplesIn):
    from .. import examples
    _db()
    return examples.save(_state["settings"].output_dir, body.model_dump())


@app.get("/api/setup")
def get_setup():
    db = _db()
    s = _state["settings"]
    st = db.get_settings()
    keys = {k.split(".", 1)[1]: st.pop(k) for k in list(st) if k.startswith("api_key.")}
    st["api_key_hint"] = {prov: ((k[:7] + "…" + k[-4:]) if len(k) > 12 else "set") for prov, k in keys.items() if k}
    st["providers"] = ["anthropic", "deepseek", "openai", "mock"]
    st["projects_csv"] = validate_projects_csv(s.projects_csv)
    st["documents"] = build_index(s.documents_dirs).summary()
    st["documents_dirs"] = [str(p) for p in s.documents_dirs]
    st["api_key_set"] = bool(s.llm.api_key)
    st["workflows"] = [w.version for w in list_workflows()]
    from ..llm import deepseek_peak_note
    st["saving"] = {"warm_cache": s.llm.warm_cache, "reuse_answers": s.llm.response_cache,
                    "codes_model": s.llm.step_models.get("codes", ""), "merge_model": s.llm.step_models.get("merge", ""),
                    "deepseek_note": deepseek_peak_note(s.llm.provider).replace("[piaa] ", "")}
    return st


@app.post("/api/setup")
def post_setup(body: SetupIn):
    cur = _db().get_settings()
    s = _state["settings"]
    provider = body.provider or cur.get("provider", "anthropic")
    same_provider = provider == cur.get("provider")
    configure(body.raw_dir or cur["raw_dir"], body.output_dir or cur["output_dir"], provider,
              body.model if body.model is not None else (cur.get("model") if same_provider else None),
              body.workflow or cur.get("workflow", "v1"),
              body.base_url if body.base_url is not None else (cur.get("base_url") if same_provider else None),
              body.api_key or None, do_reindex=False,   # "Save" only stores settings; reindexing is its own button
              saving={"warm_cache": body.warm_cache, "reuse_answers": body.reuse_answers,
                      "step_models": None if body.codes_model is None and body.merge_model is None
                      else {"codes": body.codes_model or "", "merge": body.merge_model or ""}})
    return get_setup()


@app.post("/api/setup/test")
def test_llm():
    """One tiny call with the configured provider, so a wrong key or endpoint shows up before a run."""
    s = _state["settings"]
    from ..llm import LLMClient
    try:
        client = LLMClient(s.llm)
        text = client.complete("test", "Answer with JSON only.", 'Return the JSON object {"ok": true}.', json_mode=True)
        u = client.usage()
        return {"ok": True, "provider": s.llm.provider, "model": s.llm.model, "answer": text[:120], "tokens": u}
    except Exception as e:
        return {"ok": False, "provider": s.llm.provider, "model": s.llm.model, "error": f"{type(e).__name__}: {str(e)[:300]}"}


@app.post("/api/reindex")
def post_reindex():
    _db()
    return reindex()


# ----------------------------------------------------------------------------
# database views
# ----------------------------------------------------------------------------
@app.get("/api/projects")
def api_projects():
    return _db().list_projects()


@app.get("/api/projects/{pid}")
def api_project(pid: str):
    p = _db().get_project(pid)
    if not p:
        raise HTTPException(404, f"{pid} not in projects.csv")
    p["taxonomy"] = {"pillars": [{"id": x.id, "name": x.name} for x in dai_pillars.PILLARS],
                     "solutions": [{"id": x.id, "pillar": x.pillar, "title": x.title} for x in dai_pillars.SOLUTIONS]}
    return p


@app.get("/api/projects/{pid}/document/{guid}")
def api_document(pid: str, guid: str, start: int = -1, end: int = -1, context: int = 1500):
    s = _state["settings"]
    index = build_index(s.documents_dirs)
    d = index.by_guid(guid)
    if not d:
        raise HTTPException(404)
    text = read_text(d.path)
    if start >= 0:
        a, b = max(0, start - context), min(len(text), end + context)
        return {"guid": guid, "file_name": d.file_name, "length": len(text), "window_start": a, "text": text[a:b],
                "highlight": [start - a, end - a], "verified": text[start:end] == text[start:end]}
    return {"guid": guid, "file_name": d.file_name, "length": len(text), "text": text}


@app.get("/api/projects/{pid}/context")
def api_context(pid: str, guid: str, start: int, end: int, pages: int = 2, code: str | None = None):
    """Formatted reading context (N pages) around an evidence span, built on demand."""
    from ..context import build_context
    s = _state["settings"]
    d = build_index(s.documents_dirs).by_guid(guid)
    if not d:
        raise HTTPException(404, f"document {guid} not found")
    rows = []
    p = _db().get_project(pid)
    if p and p.get("last_record"):
        rows = p["last_record"].get("aec_rows", [])
    return build_context(d, start, end, max(1, min(pages, 8)), rows, code)


class EditIn(BaseModel):
    approach_id: str | None = None
    field: str
    value: str
    reason: str = ""
    who: str = "reviewer"


@app.post("/api/projects/{pid}/edits")
def api_edit(pid: str, body: EditIn):
    db = _db()
    try:
        db.apply_edit(pid, body.approach_id, body.field, body.value, body.reason, body.who)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return db.get_project(pid)


class ManualApproachIn(BaseModel):
    name: str
    evidence_text: str = ""
    reason: str = ""
    category: str = ""
    category_solution: str = ""
    sector: str = ""
    theme: str = ""
    description: str = ""


@app.post("/api/projects/{pid}/approaches")
def api_add_approach(pid: str, body: ManualApproachIn):
    db = _db()
    aid = db.add_manual_approach(pid, body.name, body.evidence_text, body.reason, category=body.category, category_solution=body.category_solution,
                                 sector=body.sector, theme=body.theme, description=body.description)
    return {"approach_id": aid, "project": db.get_project(pid)}


class StatusIn(BaseModel):
    status: str  # pushed | reviewed | generated


@app.post("/api/projects/{pid}/status")
def api_status(pid: str, body: StatusIn):
    db = _db()
    if body.status not in ("pushed", "reviewed", "generated"):
        raise HTTPException(400, "status must be pushed | reviewed | generated")
    db.set_review_status(pid, body.status)
    return db.get_project(pid)


# ----------------------------------------------------------------------------
# workflows & runs
# ----------------------------------------------------------------------------
@app.get("/api/workflows")
def api_workflows():
    out = []
    for w in list_workflows():
        d = w.to_dict()
        d["prompts"] = w.prompts
        d["config_text"] = (w.path / "config.yaml").read_text(encoding="utf-8")
        d["changelog"] = (w.path / "CHANGELOG.md").read_text(encoding="utf-8") if (w.path / "CHANGELOG.md").exists() else ""
        d["files"] = sorted(str(p.relative_to(w.path)) for p in w.path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        out.append(d)
    return out


@app.get("/api/workflows/{version}/html", response_class=HTMLResponse)
def api_workflow_html(version: str):
    return load_workflow(version).description_html


@app.get("/api/workflows/{version}/steps")
def api_workflow_steps(version: str):
    """Flowchart data: every step with its kind, prompt files and Python source (for click-to-trace)."""
    return _steps_payload(load_workflow(version))


# ----------------------------------------------------------------------------
# code viewer: workflow folders and package modules (read-only)
# ----------------------------------------------------------------------------
PKG_ROOT = Path(__file__).resolve().parents[1]          # .../piaa
_IMPORT_RE = re.compile(r"^\s*from\s+(\.+)([\w.]*)\s+import\s+\(?([^)\n]*)", re.M)
_ABS_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(piaa(?:\.[\w]+)*)", re.M)


def _wf(kind: str, version: str):
    return load_pattern_workflow(version) if kind == "pattern" else load_workflow(version)


def _module_imports(mod_name: str, text: str) -> list[dict]:
    """piaa modules referenced by a module (relative and absolute imports)."""
    pkg = mod_name.rsplit(".", 1)[0]
    out = {}
    for dots, rest, names in _IMPORT_RE.findall(text):
        base = pkg.split(".")
        base = base[: len(base) - (len(dots) - 1)] if len(dots) > 1 else base
        target = ".".join(base + ([rest] if rest else []))
        names = [n.strip().split(" as ")[0] for n in names.replace("#", ",").split(",") if n.strip() and not n.strip().startswith("noqa")]
        if not rest:   # "from .. import x" -> x may itself be a module, else x lives in the package __init__
            for n in names:
                cand = f"{target}.{n}"
                if _module_path(cand):
                    out.setdefault(cand, [])
                else:
                    out.setdefault(target, []).append(n)
            continue
        out.setdefault(target, []).extend(names)
    for m in _ABS_IMPORT_RE.findall(text):
        out.setdefault(m, [])
    return [{"module": k, "names": v, "path": str(_module_path(k).relative_to(PKG_ROOT.parent)) if _module_path(k) else ""}
            for k, v in out.items() if k.startswith("piaa") and _module_path(k)]


def _module_path(name: str):
    if not name.startswith("piaa"):
        return None
    rel = Path(*name.split(".")[1:])
    for cand in (PKG_ROOT / rel.with_suffix(".py"), PKG_ROOT / rel / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _steps_payload(w) -> dict:
    import inspect
    mod = w.module()
    meta = w.config.get("steps_meta", {})
    mod_file = Path(inspect.getsourcefile(mod)).resolve()
    mod_text = mod_file.read_text(encoding="utf-8")
    out = []
    for name in w.config.get("steps", []):
        fn = getattr(mod, f"step_{name}", None)
        src, origin, file, line = "", "", "", 0
        if fn is not None:
            try:
                src = inspect.getsource(fn)
                origin = inspect.getmodule(fn).__name__
                file = str(Path(inspect.getsourcefile(fn)).resolve().relative_to(PKG_ROOT.parent))
                line = inspect.getsourcelines(fn)[1]
            except (OSError, TypeError, ValueError):
                pass
        m = meta.get(name, {})
        out.append({"name": name, "kind": m.get("kind", "python"), "label": m.get("label", name.replace("_", " ")),
                    "summary": m.get("summary", ""), "prompts": m.get("prompts", []), "source": src, "module": origin,
                    "file": file, "line": line, "inputs": m.get("inputs", []), "outputs": m.get("outputs", [])})
    files = sorted(str(f.relative_to(w.path)) for f in w.path.rglob("*") if f.is_file() and "__pycache__" not in f.parts)
    return {"version": w.version, "name": w.name, "hash": w.hash, "tag": w.tag, "released": w.released, "releases": w.releases, "steps": out, "prompts": w.prompts, "config": w.config,
            "folder": str(w.path.resolve().relative_to(PKG_ROOT.parent)), "files": files,
            "imports": _module_imports(mod.__name__, mod_text)}


@app.get("/api/code/file")
def api_code_file(kind: str, version: str, path: str):
    w = _wf(kind, version)
    f = (w.path / path).resolve()
    if w.path.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404, "file not in workflow folder")
    return {"path": str(f.relative_to(PKG_ROOT.parent)), "text": f.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/code/module")
def api_code_module(name: str):
    f = _module_path(name)
    if not f:
        raise HTTPException(404, f"module {name} not found in piaa")
    text = f.read_text(encoding="utf-8", errors="replace")
    return {"module": name, "path": str(f.relative_to(PKG_ROOT.parent)), "text": text, "imports": _module_imports(name if f.name != "__init__.py" else name + ".__init__", text)}


# ----------------------------------------------------------------------------
# patterns: portfolio-level replication & scaling workflows
# ----------------------------------------------------------------------------
def _wf_dict(w) -> dict:
    d = w.to_dict()
    d["prompts"] = w.prompts
    d["config_text"] = (w.path / "config.yaml").read_text(encoding="utf-8")
    d["changelog"] = (w.path / "CHANGELOG.md").read_text(encoding="utf-8") if (w.path / "CHANGELOG.md").exists() else ""
    return d


@app.get("/api/patterns/workflows")
def api_pattern_workflows():
    return [_wf_dict(w) for w in list_pattern_workflows()]


@app.get("/api/patterns/workflows/{version}/steps")
def api_pattern_steps(version: str):
    return _steps_payload(load_pattern_workflow(version))


@app.get("/api/patterns/workflows/{version}/html", response_class=HTMLResponse)
def api_pattern_html(version: str):
    return load_pattern_workflow(version).description_html


@app.get("/api/patterns/runs")
def api_pattern_runs():
    _db()
    return list_pattern_runs(_state["settings"].output_dir)


@app.get("/api/patterns/result")
def api_pattern_result(run: str | None = None):
    _db()
    res = load_pattern_result(_state["settings"].output_dir, run)
    if res is None:
        raise HTTPException(404, "no pattern run yet")
    changed = _db_last_change()
    res["db_last_change"] = changed
    res["stale"] = bool(changed and changed > (res.get("manifest") or {}).get("created_at", ""))
    return res


class PatternRunIn(BaseModel):
    workflow: str | None = None
    label: str = ""


@app.post("/api/patterns/run")
def api_pattern_run(body: PatternRunIn):
    db = _db()
    s = _state["settings"]
    job_id = uuid.uuid4().hex[:8]
    job = {"job_id": job_id, "kind": "patterns", "status": "running", "log": [], "run": None}
    _state["jobs"][job_id] = job

    def work():
        try:
            llm = None
            if s.llm.provider != "mock" and s.llm.api_key:   # any real provider (Anthropic, DeepSeek ...); the mock provider cannot judge
                from ..llm import LLMClient
                llm = LLMClient(s.llm)
            m = run_patterns(db.path, s.output_dir, body.workflow, body.label, llm=llm, progress=job["log"].append,
                             index=build_index(s.documents_dirs))   # verification reads pages around the evidence
            job["run"] = m["run"]
            job["status"] = "finished"
        except Exception as e:  # pragma: no cover
            job["status"] = f"error: {e}"

    threading.Thread(target=work, daemon=True).start()
    return job


@app.get("/api/workflows/compare")
def api_workflow_compare(a: str, b: str):
    """Structured comparison of two workflow versions: config, steps, prompts and (if available) results."""
    import difflib
    wa, wb = load_workflow(a), load_workflow(b)
    ca, cb = (wa.path / "config.yaml").read_text(encoding="utf-8"), (wb.path / "config.yaml").read_text(encoding="utf-8")
    cfg_diff = list(difflib.unified_diff(ca.splitlines(), cb.splitlines(), f"{a}/config.yaml", f"{b}/config.yaml", lineterm="", n=1))
    prompts = {}
    for key in sorted(set(wa.prompts) | set(wb.prompts)):
        pa, pb = wa.prompts.get(key), wb.prompts.get(key)
        if pa is None or pb is None:
            prompts[key] = {"status": "only_in_a" if pb is None else "only_in_b", "chars_a": len(pa or ""), "chars_b": len(pb or "")}
        else:
            ratio = difflib.SequenceMatcher(None, pa, pb).ratio()
            prompts[key] = {"status": "same" if pa == pb else "changed", "similarity": round(ratio, 3), "chars_a": len(pa), "chars_b": len(pb)}
    steps_a, steps_b = wa.config.get("steps", []), wb.config.get("steps", [])
    meta_a, meta_b = wa.config.get("steps_meta", {}), wb.config.get("steps_meta", {})
    results = {}
    db = _db()
    with db.conn() as c:
        for v in (a, b):
            r = c.execute("SELECT COUNT(DISTINCT project_id) AS projects, COUNT(*) AS runs, MAX(started_at) AS last FROM runs WHERE workflow=?", (v,)).fetchone()
            ap = c.execute("""SELECT COUNT(*) FROM approaches WHERE run_id IN (SELECT run_id FROM runs WHERE workflow=?) AND status NOT IN ('rejected','referenced_only')""", (v,)).fetchone()[0]
            inn = {x["innovative"] or "—": x["n"] for x in c.execute("SELECT innovative, COUNT(*) AS n FROM runs WHERE workflow=? GROUP BY innovative", (v,))}
            results[v] = {"projects_run": r["projects"], "runs": r["runs"], "last_run": r["last"], "approaches_headline": ap, "innovative": inn}
    return {"a": wa.to_dict() | {"changelog": (wa.path / "CHANGELOG.md").read_text(encoding="utf-8") if (wa.path / "CHANGELOG.md").exists() else "", "steps_meta": meta_a},
            "b": wb.to_dict() | {"changelog": (wb.path / "CHANGELOG.md").read_text(encoding="utf-8") if (wb.path / "CHANGELOG.md").exists() else "", "steps_meta": meta_b},
            "steps": {"a": steps_a, "b": steps_b, "only_a": [x for x in steps_a if x not in steps_b], "only_b": [x for x in steps_b if x not in steps_a], "shared": [x for x in steps_a if x in steps_b]},
            "config_diff": cfg_diff, "prompts": prompts, "results": results}


class RunIn(BaseModel):
    project_ids: list[str]
    workflow: str = "v1"
    mode: str = "refresh"       # refresh | missing | reuse
    skip_pushed: bool = True
    label: str = ""
    parallel: int = 3           # projects run at the same time (1-4); model calls inside each project are parallel too


def _require_llm_key(s) -> None:
    """Stop a run before it starts when the chosen provider has no API key (otherwise every call fails)."""
    if s.llm.provider != "mock" and not s.llm.api_key:
        raise HTTPException(400, f"No API key for provider '{s.llm.provider}'. Enter it on the Setup page (keys are stored per provider, "
                                 f"so a key saved for another provider does not carry over), or set {s.llm.key_env_var} in .env, "
                                 f"or choose provider 'mock'. Nothing was run.")


@app.post("/api/run")
def api_run(body: RunIn):
    db = _db()
    s = _state["settings"]
    _require_llm_key(s)
    busy = [j for j in _state["jobs"].values() if j.get("kind") == "approach" and j.get("status") == "running"]
    if busy:
        raise HTTPException(409, f"A run is already in progress (job {busy[0]['job_id']}, {busy[0]['done']}/{busy[0]['total']} projects). "
                                 f"Stop it first, then start a new run.")
    pushed = {p["project_id"] for p in db.list_projects() if p["review_status"] == "pushed"}
    ids = [p for p in body.project_ids if not (body.skip_pushed and p in pushed)]
    job_id = uuid.uuid4().hex[:8]
    session_id = db.create_session(body.workflow, body.mode, ids, body.label)
    job = {"job_id": job_id, "kind": "approach", "session_id": session_id, "total": len(ids), "done": 0, "status": "running", "current": None,
           "results": {}, "project_ids": ids, "skipped_pushed": sorted(set(body.project_ids) & pushed), "cancel_requested": False,
           # timing (epoch seconds, so the page can show live elapsed time with its own clock offset)
           "started_ts": time.time(), "current_started_ts": None, "ended_ts": None, "durations": {}, "server_ts": time.time()}
    _state["jobs"][job_id] = job
    cancel = threading.Event()
    _state["cancel"][job_id] = cancel

    workers = max(1, min(4, int(body.parallel or 1)))
    job.update(parallel=workers, running=[], running_started={})
    lock = threading.Lock()

    def one(pipe, pid):
        """Run (or reuse) one project; several of these run at the same time (``body.parallel``)."""
        if cancel.is_set():
            return
        t0 = time.time()
        with lock:
            job["running"].append(pid)
            job["running_started"][pid] = t0
            job["current"], job["current_started_ts"] = job["running"][0], job["running_started"][job["running"][0]]
        try:
            cached = pipe.cached(pid)
            if cached and (body.mode == "missing" or (body.mode == "reuse" and cached.input_fingerprint == pipe.input_fingerprint(pipe.projects[pid]) and not cached.error)):
                rec, res = cached, "reused"
            else:
                rec = pipe.run_project(pid)
                job["durations"][pid] = round(time.time() - t0, 1)
                if cancel.is_set():          # stopped mid-project: discard the partial result, keep the previous one
                    job["results"][pid] = "cancelled"
                    return
                res = "failed" if rec.error else "done"
            db.ingest_record(rec)
            with lock:
                job["results"][pid] = res
                job["done"] += 1
        except Exception as e:  # noqa: BLE001 - one project must not stop the others
            with lock:
                job["results"][pid] = "failed"
                job["done"] += 1
                job.setdefault("errors", {})[pid] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            with lock:
                if pid in job["running"]:
                    job["running"].remove(pid)
                job["running_started"].pop(pid, None)
                job["current"] = job["running"][0] if job["running"] else None
                job["current_started_ts"] = job["running_started"].get(job["current"]) if job["current"] else None

    def work():
        from concurrent.futures import ThreadPoolExecutor
        try:
            pipe = Pipeline(s, body.workflow)
            pipe.cancel = cancel
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(lambda pid: one(pipe, pid), ids))
            job["status"] = "cancelled" if cancel.is_set() else "finished"
            job["ended_ts"] = time.time()
        except Exception as e:  # pragma: no cover
            job["status"] = f"error: {e}"
            job["ended_ts"] = time.time()
        finally:
            job["current"] = None
            job["current_started_ts"] = None
            job["running"] = []

    threading.Thread(target=work, daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    j = _state["jobs"].get(job_id)
    if not j:
        raise HTTPException(404)
    j["server_ts"] = time.time()
    return j


@app.post("/api/jobs/{job_id}/cancel")
def api_job_cancel(job_id: str):
    """Stop button: no new project starts; model calls of the current project stop at the next call
    (a request already sent finishes first); the current project's partial result is discarded."""
    j = _state["jobs"].get(job_id)
    ev = _state["cancel"].get(job_id)
    if not j or ev is None:
        raise HTTPException(404)
    if j.get("status") == "running":
        ev.set()
        j["cancel_requested"] = True
    return j


@app.get("/api/jobs")
def api_jobs():
    return list(_state["jobs"].values())


# ----------------------------------------------------------------------------
# analytics & export
# ----------------------------------------------------------------------------
@app.get("/api/analytics")
def api_analytics():
    return _db().analytics()


@app.get("/api/analytics/v2")
def api_analytics_v2():
    """Chart blocks for the Analytics tab: sectors, AI share, categories, themes, cross-tabs."""
    return _db().analytics_v2()


class ExportIn(BaseModel):
    label: str = ""
    scope: str = "all"   # all | pushed


@app.post("/api/export")
def api_export(body: ExportIn):
    db = _db()
    s = _state["settings"]
    projects = load_projects(s.projects_csv)
    recs = db.records_for_export()
    if body.scope == "pushed":
        recs = {k: v for k, v in recs.items() if v.get("review_status") == "pushed"}
    records = {k: _record_from_dict(v) for k, v in recs.items()}
    return export_tables(records, projects, s.output_dir, body.label or body.scope)


@app.get("/api/download/database.xlsx")
def api_download_database(scope: str = "all", rejected: int = 0):
    """One Excel workbook, two tabs: Projects (projects.csv + assessment) and Approaches (project x approach,
    current database state incl. manual edits). A copy is kept in <output>/exports/."""
    from ..db_export import workbook_bytes
    db, s = _db(), _state["settings"]
    data, info = workbook_bytes(db.path, s.projects_csv, scope=scope, include_rejected=bool(rejected))
    name = f"PIA_database_{datetime.now().strftime('%Y-%m-%d_%H%M')}{'_pushed' if scope == 'pushed' else ''}.xlsx"
    try:
        out = Path(s.output_dir) / "exports"
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(data)
    except OSError:
        pass
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-PIA-Info": json.dumps(info), **_NO_CACHE})


@app.get("/api/exports")
def api_exports():
    s = _state["settings"]
    runs = s.runs_dir
    out = []
    if runs.exists():
        for f in sorted(runs.iterdir(), reverse=True):
            m = f / "run_manifest.json"
            if m.exists():
                out.append(json.loads(m.read_text(encoding="utf-8")) | {"folder": str(f)})
    return out


def main() -> None:  # entry point used by the dev supervisor (``piaa serve --dev``)
    import uvicorn
    configure(os.environ["PIAA_RAW_DIR"], os.environ["PIAA_OUTPUT_DIR"], os.environ.get("PIAA_PROVIDER") or stored_provider(os.environ["PIAA_OUTPUT_DIR"]) or "anthropic",
              os.environ.get("PIAA_MODEL") or None, os.environ.get("PIAA_WORKFLOW", "v1"))
    wfs = list_workflows()
    print(f"[piaa] PIA Review {PIAA_VERSION} · latest workflow {wfs[-1].version if wfs else '-'} · data {os.environ['PIAA_OUTPUT_DIR']}", flush=True)
    uvicorn.run(app, host=os.environ.get("PIAA_HOST", "127.0.0.1"), port=int(os.environ.get("PIAA_PORT", "18765")), log_level="warning")


if __name__ == "__main__":
    main()
