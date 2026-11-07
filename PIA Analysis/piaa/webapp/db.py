"""SQLite persistence for the review web app.

Tables
------
settings        key/value (raw_dir, output_dir, provider, model, ...)
projects        basic info from projects.csv (sectors / themes as JSON)
documents       local + API document index
runs            one row per workflow execution of a project (full record as JSON)
approaches      the *current* state of every approach (after manual edits)
field_history   every value a field has had: run results and manual edits
review          review status per project (not run | generated | reviewed | pushed)
sessions        review sessions (which projects, which workflow)

The pipeline's ProjectRecord is the unit of ingestion: :func:`ingest_record`
stores the run, rewrites the project's current approaches and appends one
history entry per field whose value changed.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import Project
from ..documents import DocumentIndex
from ..models import ProjectRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY, project_name TEXT, country TEXT, region TEXT, vertical TEXT, lead_practice TEXT,
  status TEXT, approval_date TEXT, approval_fy INTEGER, commitment_usd REAL, sectors_json TEXT, themes_json TEXT);
CREATE TABLE IF NOT EXISTS documents (
  guid TEXT PRIMARY KEY, project_id TEXT, doc_type TEXT, doc_date TEXT, file_name TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, project_id TEXT, workflow TEXT, workflow_hash TEXT, started_at TEXT, ended_at TEXT,
  innovation_tier TEXT, keyword_hits INTEGER, innovative TEXT, n_approaches INTEGER, error TEXT, record_json TEXT,
  workflow_tag TEXT, package_version TEXT);
CREATE TABLE IF NOT EXISTS approaches (
  approach_id TEXT PRIMARY KEY, project_id TEXT, run_id TEXT, n INTEGER, name TEXT, description TEXT, why_innovative TEXT,
  evidence_json TEXT, category TEXT, category_code TEXT, category_solution TEXT, category_solution_code TEXT,
  sector TEXT, theme TEXT, replication_json TEXT, status TEXT, origin TEXT, extra_json TEXT, adoption TEXT, mention_for TEXT, adoption_reason TEXT, replication_verdict TEXT);
CREATE TABLE IF NOT EXISTS field_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, approach_id TEXT, field TEXT, old_value TEXT, new_value TEXT,
  source TEXT, run_id TEXT, workflow TEXT, confidence REAL, reason TEXT, who TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS review (
  project_id TEXT PRIMARY KEY, status TEXT, session_id TEXT, innovative TEXT, notes TEXT, pushed_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, created_at TEXT, workflow TEXT, mode TEXT, project_ids_json TEXT, label TEXT);
CREATE INDEX IF NOT EXISTS ix_runs_project ON runs(project_id, started_at);
CREATE INDEX IF NOT EXISTS ix_hist ON field_history(project_id, approach_id, field, at);
"""

FIELDS = ["name", "category", "category_solution", "sector", "theme", "replication", "evidence", "status"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.conn() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(approaches)")}
            for col in ("extra_json", "adoption", "mention_for", "adoption_reason", "replication_verdict", "replication_label", "scaling_label", "pattern_run"):  # migrations for older databases
                if col not in cols:
                    c.execute(f"ALTER TABLE approaches ADD COLUMN {col} TEXT")
            rcols = {r["name"] for r in c.execute("PRAGMA table_info(runs)")}
            for col in ("workflow_tag", "package_version"):
                if col not in rcols:
                    c.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
            # label older runs with the tag of their workflow hash (releases.json)
            from ..versioning import label_run
            for r in c.execute("SELECT run_id, workflow, workflow_hash FROM runs WHERE workflow_tag IS NULL OR workflow_tag=''").fetchall():
                c.execute("UPDATE runs SET workflow_tag=? WHERE run_id=?", (label_run(r["workflow"], r["workflow_hash"]), r["run_id"]))

    @contextmanager
    def conn(self):
        with self._lock:
            c = sqlite3.connect(self.path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            try:
                yield c
                c.commit()
            finally:
                c.close()

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        with self.conn() as c:
            return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}

    def set_settings(self, values: dict) -> None:
        with self.conn() as c:
            for k, v in values.items():
                c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, "" if v is None else str(v)))

    # ------------------------------------------------------------------ catalog
    def load_catalog(self, projects: dict[str, Project], index: DocumentIndex) -> dict:
        with self.conn() as c:
            for p in projects.values():
                c.execute("""INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(project_id) DO UPDATE SET project_name=excluded.project_name, country=excluded.country, region=excluded.region,
                    vertical=excluded.vertical, lead_practice=excluded.lead_practice, status=excluded.status, approval_date=excluded.approval_date,
                    approval_fy=excluded.approval_fy, commitment_usd=excluded.commitment_usd, sectors_json=excluded.sectors_json, themes_json=excluded.themes_json""",
                          (p.project_id, p.project_name, p.country, p.region, p.vertical, p.lead_practice, p.status, p.approval_date, p.fiscal_year,
                           p.commitment_usd, json.dumps([s.to_dict() for s in p.sectors]), json.dumps([t.to_dict() for t in p.themes])))
                c.execute("INSERT OR IGNORE INTO review(project_id, status, updated_at) VALUES(?, 'not run', ?)", (p.project_id, now_iso()))
            c.execute("DELETE FROM documents")
            for pid, docs in index.by_project.items():
                for d in docs:
                    c.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?)", (d.guid, pid, d.doc_type, d.doc_date, d.file_name, d.source))
            # projects with no documents
            for pid in projects:
                if pid not in index.by_project:
                    c.execute("UPDATE review SET status='no documents', updated_at=? WHERE project_id=? AND status IN ('not run','no documents','out of scope')", (now_iso(), pid))
        return {"projects": len(projects), **index.summary()}

    # ------------------------------------------------------------------ ingest a run
    def ingest_record(self, rec: ProjectRecord, who: str = "workflow") -> None:
        d = rec.to_dict()
        with self.conn() as c:
            if c.execute("SELECT 1 FROM runs WHERE run_id=?", (rec.run_id,)).fetchone():
                return  # already ingested (idempotent for reused cache records)
            from ..versioning import label_run
            c.execute("""INSERT OR REPLACE INTO runs(run_id, project_id, workflow, workflow_hash, started_at, ended_at, innovation_tier,
                         keyword_hits, innovative, n_approaches, error, record_json, workflow_tag, package_version)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (rec.run_id, rec.project_id, rec.workflow, rec.workflow_hash, rec.started_at, rec.ended_at, rec.innovation_tier,
                       rec.innovation_keyword_hits, rec.innovative, len(rec.approaches), rec.error, json.dumps(d, ensure_ascii=False),
                       label_run(rec.workflow, rec.workflow_hash, rec.workflow_tag), rec.package_version))
            if rec.error and not rec.approaches and rec.error == "no documents":
                c.execute("UPDATE review SET status='no documents', updated_at=? WHERE project_id=?", (now_iso(), rec.project_id))
                return
            from ..scope import is_out_of_scope_error
            if is_out_of_scope_error(rec.error):   # v6.9 scope step: keep manual rows, drop earlier run results
                c.execute("DELETE FROM approaches WHERE project_id=? AND origin!='manual'", (rec.project_id,))
                c.execute("UPDATE review SET status='out of scope', innovative='', updated_at=? WHERE project_id=? AND status NOT IN ('pushed')", (now_iso(), rec.project_id))
                return
            # project-level field
            self._history(c, rec.project_id, None, "innovative", self._current_innovative(c, rec.project_id), rec.innovative, "run", rec, None, who)
            self._history(c, rec.project_id, None, "innovation_tier", None, f"{rec.innovation_tier} ({rec.innovation_keyword_hits} hits)", "run", rec, None, who)
            # replace current approaches; keep history of each field
            old = {r["approach_id"]: dict(r) for r in c.execute("SELECT * FROM approaches WHERE project_id=?", (rec.project_id,))}
            c.execute("DELETE FROM approaches WHERE project_id=? AND origin!='manual'", (rec.project_id,))
            for i, a in enumerate(rec.approaches, 1):
                ad = a.to_dict()
                vals = {
                    "name": a.name,
                    "category": a.category.value if a.category else "",
                    "category_solution": a.category_solution.value if a.category_solution else "",
                    "sector": a.sector.value if a.sector else "",
                    "theme": a.theme.value if a.theme else "",
                    "replication": "; ".join(f"{l.other_project_id} ({l.kind} {l.score:.2f})" for l in a.replication) or "none",
                    "evidence": a.evidence.text,
                    "status": a.status,
                    "adoption": (a.adoption.value if a.adoption else ""),
                }
                prev = old.get(a.approach_id, {})
                for f, v in vals.items():
                    conf = {"category": a.category, "category_solution": a.category_solution, "sector": a.sector, "theme": a.theme}.get(f)
                    self._history(c, rec.project_id, a.approach_id, f, prev.get(f) if f != "evidence" else (json.loads(prev["evidence_json"])["text"] if prev.get("evidence_json") else None),
                                  v, "run", rec, conf.confidence if conf else None, who)
                c.execute("INSERT OR REPLACE INTO approaches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (a.approach_id, rec.project_id, rec.run_id, i, a.name, a.description, a.why_innovative, json.dumps(ad["evidence"], ensure_ascii=False),
                           vals["category"], a.category.code if a.category else "", vals["category_solution"], a.category_solution.code if a.category_solution else "",
                           vals["sector"], vals["theme"], json.dumps(ad["replication"], ensure_ascii=False), a.status, "run",
                           json.dumps(ad.get("extra_evidence", []), ensure_ascii=False),
                           a.adoption.value if a.adoption else "", a.adoption.code if a.adoption else "", a.adoption.rationale if a.adoption else "", ""))
            status = "generated" if not rec.error else "failed"
            c.execute("""INSERT INTO review(project_id, status, innovative, updated_at) VALUES(?,?,?,?)
                         ON CONFLICT(project_id) DO UPDATE SET status=CASE WHEN review.status='pushed' THEN 'pushed' ELSE excluded.status END,
                         innovative=excluded.innovative, updated_at=excluded.updated_at""", (rec.project_id, status, rec.innovative, now_iso()))

    def _current_innovative(self, c, pid):
        r = c.execute("SELECT innovative FROM review WHERE project_id=?", (pid,)).fetchone()
        return r["innovative"] if r else None

    def _history(self, c, pid, aid, field, old, new, source, rec: ProjectRecord | None, confidence, who, reason=""):
        if old == new and source == "run" and field not in ("innovation_tier",):
            # still record that this run produced the same value (needed for "consistent across runs")
            pass
        c.execute("INSERT INTO field_history(project_id, approach_id, field, old_value, new_value, source, run_id, workflow, confidence, reason, who, at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, aid, field, None if old is None else str(old), None if new is None else str(new), source,
                   rec.run_id if rec else None, (rec.workflow_tag or rec.workflow) if rec else None, confidence, reason, who, now_iso()))

    # ------------------------------------------------------------------ manual edits
    def apply_edit(self, project_id: str, approach_id: str | None, field: str, value: str, reason: str, who: str = "reviewer") -> None:
        with self.conn() as c:
            if approach_id is None:
                if field == "innovative":
                    old = self._current_innovative(c, project_id)
                    c.execute("UPDATE review SET innovative=?, updated_at=? WHERE project_id=?", (value, now_iso(), project_id))
                elif field == "notes":
                    old = None
                    c.execute("UPDATE review SET notes=?, updated_at=? WHERE project_id=?", (value, now_iso(), project_id))
                else:
                    raise ValueError(f"unknown project field {field}")
            else:
                if field not in ("name", "category", "category_solution", "sector", "theme", "description", "status", "adoption", "mention_for", "replication_verdict"):
                    raise ValueError(f"field {field} is not editable")
                row = c.execute("SELECT * FROM approaches WHERE approach_id=?", (approach_id,)).fetchone()
                if not row:
                    raise KeyError(approach_id)
                old = row[field]
                c.execute(f"UPDATE approaches SET {field}=? WHERE approach_id=?", (value, approach_id))
            self._history(c, project_id, approach_id, field, old, value, "manual", None, None, who, reason)
            c.execute("UPDATE review SET status=CASE WHEN status IN ('generated','not run','failed','no documents') THEN 'reviewed' ELSE status END, updated_at=? WHERE project_id=?", (now_iso(), project_id))

    def add_manual_approach(self, project_id: str, name: str, evidence_text: str, reason: str, who: str = "reviewer", **attrs) -> str:
        with self.conn() as c:
            n = c.execute("SELECT COUNT(*) FROM approaches WHERE project_id=?", (project_id,)).fetchone()[0] + 1
            aid = f"{project_id}-M{uuid.uuid4().hex[:4]}"
            ev = {"guid": attrs.get("guid", ""), "doc_type": attrs.get("doc_type", ""), "doc_date": "", "file_name": "", "char_start": -1, "char_end": -1,
                  "text": evidence_text, "match_kind": "manual", "similarity": 0}
            c.execute("INSERT INTO approaches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, project_id, None, n, name, attrs.get("description", ""), attrs.get("why_innovative", ""), json.dumps(ev),
                       attrs.get("category", ""), "", attrs.get("category_solution", ""), "", attrs.get("sector", ""), attrs.get("theme", ""), "[]", "manual", "manual", "[]",
                       attrs.get("adoption", "applied"), "", "", ""))
            self._history(c, project_id, aid, "name", None, name, "manual", None, None, who, reason)
            c.execute("UPDATE review SET status=CASE WHEN status='pushed' THEN 'pushed' ELSE 'reviewed' END, updated_at=? WHERE project_id=?", (now_iso(), project_id))
            return aid

    # ------------------------------------------------------------------ review status
    def set_review_status(self, project_id: str, status: str, session_id: str | None = None) -> None:
        with self.conn() as c:
            c.execute("UPDATE review SET status=?, session_id=COALESCE(?, session_id), pushed_at=CASE WHEN ?='pushed' THEN ? ELSE pushed_at END, updated_at=? WHERE project_id=?",
                      (status, session_id, status, now_iso(), now_iso(), project_id))

    def create_session(self, workflow: str, mode: str, project_ids: list[str], label: str = "") -> str:
        sid = datetime.now().strftime("%Y%m%d-%H%M%S")
        with self.conn() as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)", (sid, now_iso(), workflow, mode, json.dumps(project_ids), label))
            for pid in project_ids:
                c.execute("UPDATE review SET session_id=? WHERE project_id=?", (sid, pid))
        return sid

    # ------------------------------------------------------------------ queries
    def list_projects(self) -> list[dict]:
        with self.conn() as c:
            projs = [dict(r) for r in c.execute("SELECT p.*, r.status AS review_status, r.innovative, r.session_id, r.updated_at AS last_change, r.notes FROM projects p LEFT JOIN review r USING(project_id) ORDER BY p.project_id")]
            aps = {}
            for r in c.execute("SELECT approach_id, project_id, n, name, category, category_code, category_solution, sector, theme, status, origin, replication_json, adoption, mention_for, replication_verdict, replication_label, scaling_label FROM approaches ORDER BY project_id, n"):
                aps.setdefault(r["project_id"], []).append(dict(r))
            last = {r["project_id"]: dict(r) for r in c.execute("SELECT project_id, MAX(at) AS at, source, workflow FROM field_history GROUP BY project_id")}
            runs = {r["project_id"]: r["n"] for r in c.execute("SELECT project_id, COUNT(*) AS n FROM runs GROUP BY project_id")}
        for p in projs:
            p["sectors"] = json.loads(p.pop("sectors_json") or "[]")
            p["themes"] = json.loads(p.pop("themes_json") or "[]")
            allaps = [{**a, "replication": json.loads(a.pop("replication_json") or "[]")} for a in aps.get(p["project_id"], [])]
            p["approaches"] = [a for a in allaps if a["status"] not in ("rejected", "referenced_only", "mentioned_only")]
            p["n_mentioned_only"] = sum(1 for a in allaps if a["status"] == "mentioned_only" or (a.get("adoption") == "mentioned"))
            p["n_approaches"] = len(p["approaches"]) if p["review_status"] not in ("not run", "no documents", "out of scope") else None
            p["last_change"] = last.get(p["project_id"], {})
            p["n_runs"] = runs.get(p["project_id"], 0)
        return projs

    def get_project(self, project_id: str) -> dict | None:
        with self.conn() as c:
            p = c.execute("SELECT p.*, r.status AS review_status, r.innovative, r.session_id, r.notes, r.pushed_at FROM projects p LEFT JOIN review r USING(project_id) WHERE p.project_id=?", (project_id,)).fetchone()
            if not p:
                return None
            p = dict(p)
            p["sectors"] = json.loads(p.pop("sectors_json") or "[]")
            p["themes"] = json.loads(p.pop("themes_json") or "[]")
            p["documents"] = [dict(r) for r in c.execute("SELECT * FROM documents WHERE project_id=? ORDER BY doc_type, doc_date", (project_id,))]
            p["approaches"] = []
            for r in c.execute("SELECT * FROM approaches WHERE project_id=? ORDER BY n", (project_id,)):
                a = dict(r)
                a["evidence"] = json.loads(a.pop("evidence_json") or "{}")
                a["replication"] = json.loads(a.pop("replication_json") or "[]")
                a["extra_evidence"] = json.loads(a.pop("extra_json") or "[]")
                p["approaches"].append(a)
            p["runs"] = [dict(r) for r in c.execute("SELECT run_id, workflow, workflow_tag, workflow_hash, package_version, started_at, ended_at, innovation_tier, keyword_hits, innovative, n_approaches, error FROM runs WHERE project_id=? ORDER BY started_at DESC", (project_id,))]
            p["history"] = [dict(r) for r in c.execute("SELECT * FROM field_history WHERE project_id=? ORDER BY at, id", (project_id,))]
            last = c.execute("SELECT record_json FROM runs WHERE project_id=? ORDER BY started_at DESC LIMIT 1", (project_id,)).fetchone()
            p["last_record"] = json.loads(last["record_json"]) if last else None
        return p

    def analytics_v2(self) -> dict:
        """Chart blocks for the Analytics tab (see webapp/analytics.py)."""
        from . import analytics as _an
        with self.conn() as c:
            return _an.compute(c)

    def analytics(self) -> dict:
        with self.conn() as c:
            status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) AS n FROM review GROUP BY status")}
            innov = {r["innovative"] or "—": r["n"] for r in c.execute("SELECT innovative, COUNT(*) AS n FROM review WHERE status NOT IN ('not run','no documents','out of scope') GROUP BY innovative")}
            cats = {r["category"] or "—": r["n"] for r in c.execute("SELECT category, COUNT(*) AS n FROM approaches WHERE status!='rejected' GROUP BY category ORDER BY n DESC")}
            sols = {r["category_solution"] or "—": r["n"] for r in c.execute("SELECT category_solution, COUNT(*) AS n FROM approaches WHERE status!='rejected' GROUP BY category_solution ORDER BY n DESC")}
            vert = [dict(r) for r in c.execute("""SELECT p.vertical, COUNT(DISTINCT p.project_id) AS projects,
                        SUM(CASE WHEN r.innovative='Yes' THEN 1 ELSE 0 END) AS innovative, COUNT(a.approach_id) AS approaches
                        FROM projects p LEFT JOIN review r USING(project_id) LEFT JOIN approaches a ON a.project_id=p.project_id AND a.status!='rejected'
                        GROUP BY p.vertical ORDER BY projects DESC""")]
            fy = [dict(r) for r in c.execute("""SELECT p.approval_fy AS fy, COUNT(DISTINCT p.project_id) AS projects, COUNT(a.approach_id) AS approaches
                        FROM projects p LEFT JOIN approaches a ON a.project_id=p.project_id AND a.status!='rejected' GROUP BY fy ORDER BY fy""")]
            rep = c.execute("SELECT COUNT(*) FROM approaches WHERE status!='rejected' AND replication_json!='[]'").fetchone()[0]
        return {"review_status": status, "innovative": innov, "categories": cats, "solutions": sols, "by_vertical": vert, "by_fy": fy, "approaches_with_replication": rep}

    def records_for_export(self) -> dict[str, dict]:
        """Current state per project as ProjectRecord dicts (manual edits applied)."""
        out = {}
        with self.conn() as c:
            for r in c.execute("SELECT project_id, record_json FROM runs WHERE run_id IN (SELECT run_id FROM (SELECT run_id, project_id, MAX(started_at) FROM runs GROUP BY project_id))"):
                out[r["project_id"]] = json.loads(r["record_json"])
            for pid, rec in out.items():
                cur = {a["approach_id"]: dict(a) for a in c.execute("SELECT * FROM approaches WHERE project_id=?", (pid,))}
                rv = c.execute("SELECT innovative, status FROM review WHERE project_id=?", (pid,)).fetchone()
                if rv and rv["innovative"]:
                    rec["innovative"] = rv["innovative"]
                rec["review_status"] = rv["status"] if rv else ""
                merged = []
                for a in rec["approaches"]:
                    ca = cur.pop(a["approach_id"], None)
                    if not ca:
                        continue
                    a["name"], a["status"] = ca["name"], ca["status"]
                    if ca.get("adoption"):
                        a["adoption"] = {"value": ca["adoption"], "code": ca.get("mention_for") or "", "rationale": ca.get("adoption_reason") or ""}
                    a["replication_verdict"] = ca.get("replication_verdict") or ""
                    for f in ("category", "category_solution", "sector", "theme"):
                        if a.get(f) is None:
                            a[f] = {"value": "", "code": ""}
                        a[f]["value"] = ca[f]
                    merged.append(a)
                for ca in cur.values():  # manual additions
                    merged.append({"approach_id": ca["approach_id"], "project_id": pid, "name": ca["name"], "description": ca["description"], "why_innovative": ca["why_innovative"],
                                   "evidence": json.loads(ca["evidence_json"]), "extra_evidence": [], "category": {"value": ca["category"], "code": ""},
                                   "category_solution": {"value": ca["category_solution"], "code": ""}, "sector": {"value": ca["sector"]}, "theme": {"value": ca["theme"]},
                                   "replication": [], "status": ca["status"]})
                rec["approaches"] = merged
        return out
