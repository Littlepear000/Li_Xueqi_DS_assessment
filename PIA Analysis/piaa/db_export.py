"""Download of the review database as ONE formatted Excel workbook with two tabs.

* ``Projects``   - every column of ``projects.csv`` (the original project list) plus the assessment columns
                   (review status, innovative, number of approaches, latest run / workflow tag, innovation tier).
* ``Approaches`` - one row per project x approach, the CURRENT state in the web-app database (manual edits included),
                   with all approach columns (category, solution, sector, adoption, innovation basis / cues,
                   category reason, evidence, replication ...) and the key project fields for filtering.

Rejected approaches are left out unless ``include_rejected``. ``scope="pushed"`` keeps signed-off projects only.
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

APPROACH_COLUMNS = [   # Approaches tab, in this order (0.3.18: trimmed to the columns the reviewer uses)
    "project_id", "project_name", "country", "region", "vertical", "lead_practice", "approval_date",
    "approach_id", "approach_no", "approach", "description", "why_innovative",
    "category", "sector", "adoption", "mention_for",
    "evidence_sentence", "evidence_doc_type", "evidence_doc_date", "evidence_file", "evidence_page", "n_evidence",
    "replication_verdict",
    "workflow_tag", "run_at", "run_id", "review_status", "innovative",
]
KEEP_EMPTY = {"approach_id", "approach", "evidence_page"}   # shown even when no row has a value yet
FONT = "Aptos"

# Export filter (0.3.22): the final workbook leaves out projects approved before this date,
# and projects with these statuses. Approaches of excluded projects are left out too.
MIN_APPROVAL_DATE = "2019-01-01"          # keep approval_date >= this (blank dates are kept)
EXCLUDE_STATUS = {"dropped", "canceled", "cancelled"}
WIDE = {"approach": 42, "description": 60, "why_innovative": 50, "innovation_basis": 45, "category_reason": 40,
        "evidence_sentence": 80, "replication_links": 40, "project_name": 34, "sector_names": 50, "themes": 60,
        "sector_percents": 22, "evidence_file": 34, "lead_practice": 26, "country": 18, "region": 24}


def _j(text, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def build_tables(db_path: str | Path, projects_csv: str | Path, scope: str = "all", include_rejected: bool = False):
    c = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        review = pd.read_sql("SELECT project_id, status AS review_status, innovative FROM review", c)
        A = pd.read_sql("SELECT * FROM approaches", c)
        R = pd.read_sql("SELECT project_id, run_id, workflow, workflow_tag, started_at, innovation_tier, keyword_hits, record_json FROM runs", c)
    finally:
        c.close()
    R = R.sort_values("started_at").groupby("project_id").tail(1).set_index("project_id")
    extra = {}
    for _, row in R.iterrows():
        for a in _j(row.record_json, {}).get("approaches", []):
            extra[a.get("approach_id")] = {"innovation_basis": a.get("innovation_basis", ""),
                                           "innovation_cues": "; ".join(a.get("innovation_cues") or []),
                                           "category_reason": (a.get("category") or {}).get("rationale", "")}
    runs_by_id = {}
    for pid, row in R.iterrows():
        runs_by_id[row.run_id] = (row.workflow_tag or row.workflow, row.started_at)

    # ---------------- Projects: projects.csv as is + assessment columns
    P = pd.read_csv(projects_csv, dtype=str).fillna("")
    P = P.drop_duplicates("project_id", keep="first")  # dedup like load_projects (first row wins); projects.csv may list an id twice
    P = P.merge(review, on="project_id", how="left")
    live = A[A["status"].fillna("") != "rejected"]
    P["n_approaches"] = P["project_id"].map(live.groupby("project_id").size()).fillna(0).astype(int)
    P["latest_workflow_tag"] = P["project_id"].map(R["workflow_tag"]).fillna("")
    P["latest_run_at"] = P["project_id"].map(R["started_at"]).fillna("").str.replace("T", " ").str.replace("Z", "")
    P["innovation_tier"] = P["project_id"].map(R["innovation_tier"]).fillna("")
    P["innovation_keyword_hits"] = P["project_id"].map(R["keyword_hits"])
    if "commitment_usd" in P:
        P["commitment_usd"] = pd.to_numeric(P["commitment_usd"].str.replace(",", ""), errors="coerce")

    # ---------------- Approaches
    D = A if include_rejected else live
    D = D.merge(P[[c for c in ("project_id", "project_name", "country", "region", "vertical", "lead_practice", "approval_date",
                               "review_status", "innovative") if c in P]], on="project_id", how="left")
    ev = D["evidence_json"].map(lambda t: _j(t, {}))
    D = D.assign(
        approach=D["name"], approach_no=D["n"], solution=D["category_solution"], solution_code=D["category_solution_code"],
        approach_status=D["status"],
        innovation_basis=D["approach_id"].map(lambda x: extra.get(x, {}).get("innovation_basis", "")),
        innovation_cues=D["approach_id"].map(lambda x: extra.get(x, {}).get("innovation_cues", "")),
        category_reason=D["approach_id"].map(lambda x: extra.get(x, {}).get("category_reason", "")),
        evidence_sentence=ev.map(lambda e: e.get("text", "")), evidence_doc_type=ev.map(lambda e: e.get("doc_type", "")),
        evidence_doc_date=ev.map(lambda e: e.get("doc_date", "")), evidence_file=ev.map(lambda e: e.get("file_name", "")),
        # page of the evidence in the source document: the local .txt files carry no page breaks, so this stays empty
        # until page numbers are available (e.g. from the PDF); the column is kept so it can be filled later
        evidence_page=ev.map(lambda e: e.get("page", "")),
        n_evidence=1 + D["extra_json"].map(lambda t: len(_j(t, []))),
        replication_links=D["replication_json"].map(lambda t: "; ".join(
            f"{l.get('other_project_id', '')} ({l.get('kind', '')}, {float(l.get('score') or 0):.2f})" for l in _j(t, []) if isinstance(l, dict))),
        workflow_tag=D["run_id"].map(lambda r: runs_by_id.get(r, ("", ""))[0]),
        run_at=D["run_id"].map(lambda r: str(runs_by_id.get(r, ("", ""))[1] or "").replace("T", " ").replace("Z", "")),
    )
    cols = list(APPROACH_COLUMNS)
    if include_rejected:   # rejected rows must stay distinguishable: keep their status next to adoption
        cols.insert(cols.index("adoption") + 1, "approach_status")
    D = D[[c for c in cols if c in D.columns]].sort_values(["project_id", "approach_no"])
    # drop columns that are empty for every row (e.g. theme for v6.1+ results only)
    D = D[[c for c in D.columns if D[c].fillna("").astype(str).str.strip().ne("").any() or c in KEEP_EMPTY]]
    # --- filter: drop pre-2019 approvals and dropped/canceled projects (0.3.22) ---
    status_l = P["status"].fillna("").astype(str).str.strip().str.lower() if "status" in P else ""
    date_s = P["approval_date"].fillna("").astype(str).str.strip() if "approval_date" in P else ""
    keep = ~status_l.isin(EXCLUDE_STATUS)
    if MIN_APPROVAL_DATE and "approval_date" in P:
        # keep rows with a blank/unparseable date; drop only those clearly before the cutoff
        keep &= ~((date_s.str.len() >= 10) & (date_s.str[:10] < MIN_APPROVAL_DATE))
    kept_ids = set(P.loc[keep, "project_id"])
    P = P[keep]
    D = D[D["project_id"].isin(kept_ids)]

    if scope == "pushed":
        P = P[P["review_status"] == "pushed"]
        D = D[D["review_status"] == "pushed"]
    return P.reset_index(drop=True), D.reset_index(drop=True)


def _format(ws, df: pd.DataFrame, wrap_rows: float | None = None) -> None:
    """Header style, frozen ID columns, filters, column widths. ``wrap_rows``: wrap long text and fix every data
    row to this height (points) so rows stay even; None = no wrapping (one line per row)."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    head_fill = PatternFill("solid", fgColor="1F3A68")
    body_font = Font(name=FONT, size=11)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = body_font
    for cell in ws[1]:
        cell.font = Font(name=FONT, size=11, bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    if wrap_rows:
        for r in range(2, ws.max_row + 1):
            ws.row_dimensions[r].height = wrap_rows
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    for k, col in enumerate(df.columns, 1):
        letter = get_column_letter(k)
        sample = df[col].head(300).fillna("").astype(str)
        longest = max([len(str(col))] + [len(x) for x in sample]) if len(sample) else len(str(col))
        width = WIDE.get(col, min(max(10, longest + 2), 30))
        ws.column_dimensions[letter].width = width
        wrap = bool(wrap_rows) and width >= 34
        for cell in ws[letter][1:]:
            cell.alignment = Alignment(vertical="top", wrap_text=wrap)
        if col in ("commitment_usd",):
            for cell in ws[letter][1:]:
                cell.number_format = "#,##0"


def workbook_bytes(db_path, projects_csv, scope: str = "all", include_rejected: bool = False) -> tuple[bytes, dict]:
    P, D = build_tables(db_path, projects_csv, scope, include_rejected)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        P.to_excel(xw, sheet_name="Projects", index=False)
        D.to_excel(xw, sheet_name="Approaches", index=False)
        _format(xw.sheets["Projects"], P)                     # one line per project (long sector / theme lists stay on one line)
        _format(xw.sheets["Approaches"], D, wrap_rows=60)     # text columns wrapped, rows ~4 lines high
    info = {"projects": int(len(P)), "approaches": int(len(D)), "projects_with_approaches": int(D["project_id"].nunique()) if len(D) else 0,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M")}
    return buf.getvalue(), info
