"""Analysis mart: an approach-level, analysis-ready database built from the review DB.

Source of truth is the review database (``output/pia_review.db``), i.e. whatever is
the latest state of every project - workflow output plus any reviewer edits.
Only approaches with ``status != 'rejected'`` enter the analysis.

Weighting logic (one place, documented)
---------------------------------------
For a project *p* with commitment ``C_p``, ``n_p`` retained approaches and sector
shares ``s_{p,k}`` (normalised to sum to 1):

* ``commitment_weight``        = C_p * s_{p,k}              (per approach x sector row)  <-- DEFAULT sector weight
  -> an approach counts in sector k with the dollars the project allocates to k. This is the
     agreed sector methodology: the project's commitment is split across its sectors by the
     coded percentages, and that dollar amount, not the bare percentage, weights the approach.
     Summing over sectors gives C_p per approach; summing over the approaches of one project
     gives n_p * C_p, so totals are "dollar-weighted approach counts", not disbursable amounts.
     Projects with no commitment amount carry zero weight (reported as coverage).
  (column name in the bridge: ``exposure_commitment``, kept for backward compatibility)
* ``approach_weight``          = 1 / n_p
* ``attributed_commitment``    = C_p * s_{p,k} / n_p        (per approach x sector row)
  -> additive: summing over all approaches and sectors of a project returns C_p,
     so dollar totals never double count.  Use when the question is "how much lending sits
     behind approaches of type X", not "how heavy is sector k".
* ``weighted_count``           = s_{p,k}                    (per approach x sector row)
  -> plain sector-share-weighted approach count; sums to the number of approaches.
     Kept as the count-based, commitment-free view (covers projects with no commitment).

Themes are coded independently (a project can be 100% ICT and 93% Data at the same
time), so theme rows use ``theme_intensity = pct / 100`` and are NOT additive across
themes.  Per theme group the intensity is the max over its level-2 themes.

Tables written to ``mart.sqlite`` (and as CSV):
  dim_project, project_sector, project_theme, fact_approach,
  bridge_approach_sector, bridge_approach_theme
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..taxonomy.dai_pillars import SOLUTION_BY_ID
from ..versioning import package_version
from .crosswalks import fy_period, major_sector, region_group, size_band, tech_archetype, theme_group

PILLAR_ORDER = ["P1", "P2", "P3", "P4", "PX"]
PILLAR_NAME = {"P1": "Access", "P2": "Affordability", "P3": "Ecosystem",
               "P4": "AI Readiness and Adaptation", "PX": "Digital Trust (cross-cutting)",
               "NONE": "Not mapped to the Plan"}
NO_SOLUTION = "No D&AI solution (not mapped)"


def _read(db_path: Path) -> dict[str, pd.DataFrame]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {t: pd.read_sql(f"SELECT * FROM {t}", con)
                for t in ("projects", "approaches", "runs", "review")}
    finally:
        con.close()


def _latest_runs(runs: pd.DataFrame) -> pd.DataFrame:
    runs = runs.sort_values("started_at")
    return runs.groupby("project_id", as_index=False).tail(1).set_index("project_id")


def build_mart(db_path: str | Path, out_dir: str | Path, label: str = "") -> Path:
    db_path, out_dir = Path(db_path), Path(out_dir)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = out_dir / f"{stamp}{'_' + label if label else ''}"
    folder.mkdir(parents=True, exist_ok=True)
    src = _read(db_path)
    P, A, R, V = src["projects"], src["approaches"], _latest_runs(src["runs"]), src["review"].set_index("project_id")

    # ------------------------------------------------------------------ approaches retained
    A = A[A["status"].fillna("") != "rejected"].copy()
    # Strict hierarchy (D&AI Implementation Plan FY26-30): every solution belongs to exactly one
    # pillar, so the pillar is DERIVED from the solution, never taken independently.
    #   P1 Access: S1-S2 | P2 Affordability: S3-S5 | P3 Ecosystem: S6-S8 | P4 AI Readiness: S9-S10
    #   PX Digital Trust (cross-cutting layer, package extension): SX
    # The model's own pillar is kept as pillar_code_raw; disagreements are flagged for review.
    # Approaches with no valid solution get no pillar ("NONE" = not mapped to the Plan).
    raw = A["category_code"].fillna("NONE").str.upper()
    cat = A["category"].fillna("").str.strip().str.lower()
    A["pillar_code_raw"] = raw.where(~cat.isin(["none", ""]) & raw.isin(PILLAR_ORDER), "NONE")
    sol = A["category_solution_code"].fillna("").str.upper()
    A["solution_code"] = sol.where(sol.isin(list(SOLUTION_BY_ID)), "NONE")
    A["solution"] = A["solution_code"].map(lambda c: SOLUTION_BY_ID[c].title if c in SOLUTION_BY_ID else NO_SOLUTION)
    A["pillar_code"] = A["solution_code"].map(lambda c: SOLUTION_BY_ID[c].pillar if c in SOLUTION_BY_ID else "NONE")
    A["pillar"] = A["pillar_code"].map(PILLAR_NAME)
    A["mapping_status"] = "consistent"
    A.loc[(A["solution_code"] != "NONE") & (A["pillar_code_raw"] != A["pillar_code"]), "mapping_status"] = "pillar_overridden_by_solution"
    A.loc[(A["solution_code"] == "NONE") & (A["pillar_code_raw"] != "NONE"), "mapping_status"] = "pillar_without_solution"
    A.loc[(A["solution_code"] == "NONE") & (A["pillar_code_raw"] == "NONE"), "mapping_status"] = "not_mapped"
    ev = A["evidence_json"].fillna("{}").map(json.loads)
    A["evidence_doc_type"] = ev.map(lambda e: e.get("doc_type", ""))
    A["evidence_doc_date"] = ev.map(lambda e: e.get("doc_date", ""))
    A["evidence_stage"] = A["evidence_doc_type"].map(
        lambda t: "Implementation (ISR)" if t == "ISR" else ("Design (PAD/PID/Paper)" if t else "n/a"))
    rep = A["replication_json"].fillna("[]").map(json.loads)
    A["replicated"] = rep.map(lambda r: len(r) > 0)
    A["replication_links"] = rep.map(lambda r: ";".join(sorted({x.get("project_id", "") for x in r if isinstance(x, dict)})))
    A["tech_archetype"] = (A["name"].fillna("") + " " + A["description"].fillna("")).map(tech_archetype)
    n_by_project = A.groupby("project_id")["approach_id"].count()

    # ------------------------------------------------------------------ projects
    D = P.copy()
    D["region_group"] = D["region"].map(region_group)
    D["size_band"] = D["commitment_usd"].map(size_band)
    D["fy_period"] = D["approval_fy"].map(fy_period)
    D["innovative"] = D["project_id"].map(V["innovative"]).fillna("")
    D["review_status"] = D["project_id"].map(V["status"]).fillna("")
    D["innovation_tier"] = D["project_id"].map(R["innovation_tier"]).fillna("")
    D["keyword_hits"] = D["project_id"].map(R["keyword_hits"])
    D["workflow"] = D["project_id"].map(R["workflow"]).fillna("")
    if "workflow_tag" in R.columns:
        D["workflow_tag"] = D["project_id"].map(R["workflow_tag"]).fillna("")
    D["n_approaches"] = D["project_id"].map(n_by_project).fillna(0).astype(int)
    D["has_approach"] = D["n_approaches"] > 0
    D["analysed"] = D["review_status"].isin(["generated", "reviewed", "pushed"])

    # ------------------------------------------------------------------ project sectors / themes
    ps_rows, pt_rows = [], []
    for _, p in D.iterrows():
        secs = json.loads(p["sectors_json"] or "[]")
        tot = sum(float(s.get("pct") or 0) for s in secs)
        for s in secs:
            pct = float(s.get("pct") or 0)
            ps_rows.append({"project_id": p["project_id"], "sector": s["name"], "major_sector": major_sector(s["name"]),
                            # all-zero percentages (e.g. dropped projects): split equally across listed sectors
                            "sector_pct": pct, "sector_share": pct / tot if tot else 1.0 / len(secs),
                            "code_version": s.get("code_version", "")})
        for t in json.loads(p["themes_json"] or "[]"):
            l1, _, l2 = t["name"].partition(" > ")
            pt_rows.append({"project_id": p["project_id"], "theme": t["name"], "theme_l1": l1, "theme_l2": l2,
                            "theme_group": theme_group(l1, l2), "theme_pct": float(t.get("pct") or 0),
                            "code_version": t.get("code_version", "")})
    PS, PT = pd.DataFrame(ps_rows), pd.DataFrame(pt_rows)
    # Projects without sector codes get one "Unspecified" row so dollars are not lost.
    missing = set(D["project_id"]) - set(PS.loc[PS["sector_share"] > 0, "project_id"])
    if missing:
        PS = PS[~PS["project_id"].isin(missing)]
        PS = pd.concat([PS, pd.DataFrame([{"project_id": m, "sector": "Unspecified", "major_sector": "Unspecified",
                                           "sector_pct": 100.0, "sector_share": 1.0, "code_version": ""} for m in missing])])
    PS = PS[PS["sector_share"] > 0]
    lead = PS.sort_values("sector_share", ascending=False).groupby("project_id").head(1).set_index("project_id")
    maj = PS.groupby(["project_id", "major_sector"], as_index=False)["sector_share"].sum()
    lead_major = maj.sort_values("sector_share", ascending=False).groupby("project_id").head(1).set_index("project_id")
    D["lead_sector"] = D["project_id"].map(lead["sector"])
    D["lead_major_sector"] = D["project_id"].map(lead_major["major_sector"])
    D["lead_major_sector_share"] = D["project_id"].map(lead_major["sector_share"])

    # ------------------------------------------------------------------ fact_approach
    pcols = ["project_id", "project_name", "country", "region", "region_group", "vertical", "lead_practice",
             "status", "approval_fy", "fy_period", "commitment_usd", "size_band", "innovative",
             "innovation_tier", "lead_major_sector", "n_approaches"]
    F = A.merge(D[pcols], on="project_id", how="left")
    F["approach_weight"] = 1.0 / F["n_approaches"]
    F["attributed_commitment"] = F["commitment_usd"].fillna(0) * F["approach_weight"]
    F = F.rename(columns={"name": "approach", "sector": "matched_sector", "theme": "matched_theme",
                          "status_x": "approach_status", "status_y": "project_status"})
    F = F.drop(columns=["evidence_json", "replication_json"])

    # ------------------------------------------------------------------ bridges
    keep = ["approach_id", "project_id", "pillar_code", "pillar", "solution_code", "solution", "region_group",
            "approval_fy", "fy_period", "size_band", "commitment_usd", "approach_weight", "evidence_stage", "replicated",
            "tech_archetype"]
    BS = F[keep].merge(PS[["project_id", "sector", "major_sector", "sector_share"]], on="project_id")
    BS["weighted_count"] = BS["sector_share"]
    BS["attributed_commitment"] = BS["commitment_usd"].fillna(0) * BS["sector_share"] * BS["approach_weight"]
    BS["exposure_commitment"] = BS["commitment_usd"].fillna(0) * BS["sector_share"]
    BS["commitment_weight"] = BS["exposure_commitment"]  # default sector weight (see module docstring)

    BT = F[keep].merge(PT[["project_id", "theme", "theme_l1", "theme_l2", "theme_group", "theme_pct"]], on="project_id")
    BT["theme_intensity"] = BT["theme_pct"] / 100.0
    BT["weighted_count"] = BT["theme_intensity"]
    BT["attributed_commitment"] = BT["commitment_usd"].fillna(0) * BT["theme_intensity"] * BT["approach_weight"]

    # ------------------------------------------------------------------ write
    D_out = D.drop(columns=["sectors_json", "themes_json"])
    tables = {"dim_project": D_out, "project_sector": PS, "project_theme": PT, "fact_approach": F,
              "bridge_approach_sector": BS, "bridge_approach_theme": BT}
    # SQLite is written to a local temp file first: synced / network folders often refuse its journal.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "mart.sqlite"
        con = sqlite3.connect(tmp_db)
        try:
            for name, df in tables.items():
                df.to_sql(name, con, index=False, if_exists="replace")
                df.to_csv(folder / f"{name}.csv", index=False)
            con.commit()
        finally:
            con.close()
        shutil.copyfile(tmp_db, folder / "mart.sqlite")
    manifest = {"created": datetime.now().isoformat(timespec="seconds"), "source_db": str(db_path),
                "source_db_modified": datetime.fromtimestamp(db_path.stat().st_mtime).isoformat(timespec="seconds"),
                "rows": {k: int(len(v)) for k, v in tables.items()},
                "projects_analysed": int(D["analysed"].sum()), "projects_with_approach": int(D["has_approach"].sum()),
                "approaches_retained": int(len(F)), "approaches_rejected": int((src["approaches"]["status"] == "rejected").sum()),
                "package_version": package_version(),
                "source_workflow_tags": (D.loc[D["analysed"], "workflow_tag"].value_counts().to_dict() if "workflow_tag" in D.columns else {})}
    (folder / "mart_manifest.json").write_text(json.dumps(manifest, indent=2))
    return folder
