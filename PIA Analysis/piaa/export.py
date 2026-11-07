"""Build the two output tables from project records and write them to disk.

Table 1 - ``projects``   : one row per project analysed.
Table 2 - ``approaches`` : one row per project x approach, with the evidence
sentence, the document it comes from and the classified attributes.

Every export goes into a new time-stamped folder under ``output_dir/runs/``;
earlier exports are never overwritten.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .catalog import Project
from .models import ProjectRecord
from .versioning import package_version


def projects_table(records: dict[str, ProjectRecord], projects: dict[str, Project]) -> pd.DataFrame:
    rows = []
    for pid, rec in records.items():
        p = projects.get(pid)
        live = [a for a in rec.approaches if a.status not in ("rejected", "referenced_only", "mentioned_only")]
        rows.append({
            "project_id": pid,
            "project_name": p.project_name if p else "",
            "country": p.country if p else "",
            "region": p.region if p else "",
            "vertical": p.vertical if p else "",
            "lead_practice": p.lead_practice if p else "",
            "status": p.status if p else "",
            "approval_date": p.approval_date if p else "",
            "approval_fy": p.fiscal_year if p else None,
            "commitment_usd": p.commitment_usd if p else None,
            "lead_sector": p.sectors[0].name if p and p.sectors else "",
            "lead_theme": p.themes[0].name if p and p.themes else "",
            "documents_used": "; ".join(f"{d['doc_type']} {d['doc_date']}" for d in rec.documents_used),
            "innovation_keyword_hits": rec.innovation_keyword_hits,
            "innovation_tier": rec.innovation_tier,
            "innovative": rec.innovative,
            "n_approaches": len(live),
            "n_mentioned_only": sum(1 for a in rec.approaches if a.status == "mentioned_only"),
            "n_evidence": sum(1 + len(a.extra_evidence) for a in rec.approaches),
            "approaches": " | ".join(a.name for a in live),
            "categories": " | ".join(sorted({a.category.value for a in live if a.category})),
            "replicates_other_project": any(l.direction == "replicates" for a in live for l in a.replication),
            "workflow": rec.workflow,
            "workflow_tag": rec.workflow_tag,
            "workflow_hash": rec.workflow_hash,
            "package_version": rec.package_version,
            "run_id": rec.run_id,
            "run_time": rec.ended_at,
            "error": rec.error,
        })
    return pd.DataFrame(rows)


MAX_EVIDENCE_COLUMNS = 10


def approaches_table(records: dict[str, ProjectRecord], projects: dict[str, Project], expand_evidence: bool = True) -> pd.DataFrame:
    rows = []
    for pid, rec in records.items():
        p = projects.get(pid)
        for a in rec.approaches:
            best = max(a.replication, key=lambda l: l.score, default=None)
            evs = [a.evidence] + list(a.extra_evidence)
            n_rows = sum(1 for r in rec.aec_rows if r.get("approach_id") == a.approach_id)
            ev_cols = {}
            if expand_evidence:
                for k, e in enumerate(evs[:MAX_EVIDENCE_COLUMNS], 1):
                    ev_cols[f"evidence_{k}_sentence"] = e.text
                    ev_cols[f"evidence_{k}_document"] = f"{e.doc_type} {e.doc_date} ({e.file_name})"
                    ev_cols[f"evidence_{k}_position"] = f"chars {e.char_start}-{e.char_end}"
                if len(evs) > MAX_EVIDENCE_COLUMNS:
                    ev_cols["evidence_more"] = f"+{len(evs) - MAX_EVIDENCE_COLUMNS} more in the approach_evidence table"
            rows.append({
                "project_id": pid,
                "approach_id": a.approach_id,
                "project_name": p.project_name if p else "",
                "country": p.country if p else "",
                "region": p.region if p else "",
                "vertical": p.vertical if p else "",
                "lead_practice": p.lead_practice if p else "",
                "project_status": p.status if p else "",
                "approval_date": p.approval_date if p else "",
                "approval_fy": p.fiscal_year if p else None,
                "commitment_usd": p.commitment_usd if p else None,
                "project_sectors": "; ".join(f"{x.name} ({x.pct:g}%)" if x.pct is not None else x.name for x in (p.sectors if p else [])),
                "project_themes": "; ".join(f"{x.name} ({x.pct:g}%)" if x.pct is not None else x.name for x in (p.themes if p else [])),
                "review_status": getattr(rec, "review_status", "") or "",
                "headline": a.status == "validated",
                "approach": a.name,
                "number_of_evidence": max(len(evs), n_rows),
                "description": a.description,
                "why_innovative": a.why_innovative,
                "innovation_basis": a.innovation_basis,
                "innovation_cues": "; ".join(a.innovation_cues),
                "evidence_sentence": a.evidence.text,
                "document": a.evidence.file_name,
                "document_type": a.evidence.doc_type,
                "document_date": a.evidence.doc_date,
                "document_guid": a.evidence.guid,
                "char_start": a.evidence.char_start,
                "char_end": a.evidence.char_end,
                "evidence_match": a.evidence.match_kind,
                "category": a.category.value if a.category else "",
                "category_code": a.category.code if a.category else "",
                "category_confidence": a.category.confidence if a.category else None,
                "category_validation": a.category.validated if a.category else "",
                "category_solution": a.category_solution.value if a.category_solution else "",
                "category_solution_code": a.category_solution.code if a.category_solution else "",
                "sector": a.sector.value if a.sector else "",
                "sector_validation": a.sector.validated if a.sector else "",
                "theme": a.theme.value if a.theme else "",
                "theme_validation": a.theme.validated if a.theme else "",
                "adoption": a.adoption.value if a.adoption else "",
                "mention_for": a.adoption.code if a.adoption else "",
                "adoption_reason": a.adoption.rationale if a.adoption else "",
                "replicated": bool(a.replication),
                "replication_links": "; ".join(f"{l.other_project_id} ({l.kind}, {l.score:.2f}, {l.direction})" for l in a.replication),
                "replication_best_project": best.other_project_id if best else "",
                "replication_best_score": best.score if best else None,
                "replication_verdict": getattr(a, "replication_verdict", "") or "",
                "status": a.status,
                "workflow": rec.workflow,
                "run_id": rec.run_id,
                **ev_cols,
            })
    df = pd.DataFrame(rows)
    # workflows without approach-level themes (v6.1+): leave the theme columns out instead of exporting them empty
    theme_cols = [c for c in ("theme", "theme_validation") if c in df.columns]
    if len(df) and theme_cols and not df[theme_cols].fillna("").astype(str).apply(lambda c: c.str.strip()).ne("").any().any():
        df = df.drop(columns=theme_cols)
    return df


def aec_table(records: dict[str, ProjectRecord]) -> pd.DataFrame:
    rows = [r for rec in records.values() for r in rec.aec_rows]
    return pd.DataFrame(rows)


def exclusion_table(records: dict[str, ProjectRecord]) -> pd.DataFrame:
    rows = [{"project_id": pid, **r} for pid, rec in records.items() for r in rec.exclusion_log]
    return pd.DataFrame(rows)


DATA_DICTIONARY = [
    ("project_approaches", "project_id", "World Bank project ID (join key to projects.csv and document file names)"),
    ("project_approaches", "approach_id", "project_id + DDAT approach code (v2/v3) or sequence number (v1)"),
    ("project_approaches", "approach", "DDAT approach: code + name (v2/v3) or model-named approach (v1)"),
    ("project_approaches", "headline", "True when the row counts in headline figures: adoption = apply (v4) / applied and L2-L3 (v3)"),
    ("project_approaches", "number_of_evidence", "Number of evidence passages collapsed into this approach (same category, sector, theme)"),
    ("project_approaches", "evidence_k_sentence / _document / _position", "Evidence passages expanded into columns (k = 1..10); all passages are in approach_evidence"),
    ("project_approaches", "status", "validated | mentioned_only | referenced_only (L1 only) | rejected"),
    ("project_approaches", "adoption", "v4: apply | prospect | discuss (apply = this project finances / implements it; prospect = envisaged for the future; discuss = discussed, lessons, options). v3: applied | mentioned"),
    ("project_approaches", "mention_for", "future_plan | aspiration_or_vision | other_program | lesson_or_reference | option_considered | parent_or_prior | unclear"),
    ("project_approaches", "evidence_sentence", "Verbatim sentence from the source document (char_start/char_end anchor it in the file)"),
    ("project_approaches", "category / category_code", "v4: working-paper innovation category - Operational | Technological | Financial | Collaborative. v1-v3: Digital & AI Implementation Plan pillar"),
    ("project_approaches", "category_solution / category_solution_code", "Solution S1-S10 / TRUST, via Methodology Note 2 mapping (direct or model choice)"),
    ("project_approaches", "sector", "v4: the ONE sector from the project's projects.csv list that the approach most directly serves. v3: lead sector"),
    ("project_approaches", "theme", "v4: the ONE theme from the project's projects.csv list that the approach most directly advances. v3: DDAT parent theme"),
    ("project_approaches", "replication_links", "Other in-scope projects linked: explicit_reference or similar_approach, score, direction (replicates = this project is later)"),
    ("project_approaches", "replication_verdict", "Reviewer verdict on the links: confirmed | rejected | unsure (set in the web app)"),
    ("project_approaches", "innovation_basis", "v6: one line naming what is new (product / service / process / delivery arrangement / organizational practice) and the words that show it"),
    ("project_approaches", "innovation_cues", "v6: innovation-dictionary hits (non-technology dimensions: innovation, innovation_cycle, results-based management, innovation types, enabling processes, public good) in the approach's evidence units - a signal, not a gate"),
    ("projects", "innovation_tier", "Project-level screen (v1, v6): distinct innovation-dictionary hits across all 7 dimensions in the project's documents - High >= 4, Moderate 2-3, Low 0-1"),
    ("projects", "n_approaches", "Headline approaches (applied, L2/L3); n_mentioned_only = approaches only mentioned"),
    ("approach_evidence", "(row)", "One row per evidence passage: approach_id, evidence_no, number_of_evidence, verbatim sentence, document, char offsets, adoption of the passage, label, reason"),
    ("exclusion_log", "(row)", "Candidate sentences the model rejected, with the reason - kept so a reviewer can restore them"),
    ("exclusion_log", "reject_code", "v6: generic | not_digital | not_innovative | legal_or_compliance_condition | background_or_other_programme | unsupported_by_evidence"),
    ("approach_evidence", "evidence_source", "v6: body | legal_condition (a PAD Data Sheet sentence attached to an approach found in the body)"),
]


def export(records: dict[str, ProjectRecord], projects: dict[str, Project], output_dir: str | Path, label: str = "") -> dict:
    """Write both tables (xlsx + csv) and a manifest into a new versioned run folder."""
    output_dir = Path(output_dir)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = output_dir / "runs" / (f"{stamp}_{label}" if label else stamp)
    folder.mkdir(parents=True, exist_ok=True)
    t1, t2 = projects_table(records, projects), approaches_table(records, projects)
    paths = {
        "approaches_csv": folder / "table1_project_approaches.csv",   # the database: one row per project x approach
        "projects_csv": folder / "table2_projects.csv",                # project-level summary (what the web app lists)
        "xlsx": folder / "pia_analysis.xlsx",
        "manifest": folder / "run_manifest.json",
    }
    t2.to_csv(paths["approaches_csv"], index=False)
    t1.to_csv(paths["projects_csv"], index=False)
    t3, t4 = aec_table(records), exclusion_table(records)
    if len(t3):
        paths["aec_csv"] = folder / "table3_approach_evidence.csv"
        t3.to_csv(paths["aec_csv"], index=False)
    if len(t4):
        paths["exclusions_csv"] = folder / "table4_exclusion_log.csv"
        t4.to_csv(paths["exclusions_csv"], index=False)
    with pd.ExcelWriter(paths["xlsx"], engine="openpyxl") as xw:
        t2.to_excel(xw, sheet_name="project_approaches", index=False)
        t1.to_excel(xw, sheet_name="projects", index=False)
        if len(t3):
            t3.drop(columns=[c for c in ("context_before", "context_after") if c in t3.columns]).to_excel(xw, sheet_name="approach_evidence", index=False)
        if len(t4):
            t4.to_excel(xw, sheet_name="exclusion_log", index=False)
        pd.DataFrame(DATA_DICTIONARY, columns=["sheet", "column", "meaning"]).to_excel(xw, sheet_name="data_dictionary", index=False)
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"), "label": label,
        "projects": len(t1), "approaches": len(t2), "headline_approaches": int(t2["headline"].sum()) if len(t2) else 0, "aec_rows": len(t3), "excluded": len(t4),
        "innovative_counts": t1["innovative"].value_counts().to_dict() if len(t1) else {},
        "workflows": sorted(t1["workflow"].unique().tolist()) if len(t1) else [],
        "workflow_tags": t1["workflow_tag"].value_counts().to_dict() if len(t1) and "workflow_tag" in t1 else {},
        "package_version": package_version(),
        "files": {k: str(v) for k, v in paths.items()},
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["folder"] = str(folder)
    return manifest
