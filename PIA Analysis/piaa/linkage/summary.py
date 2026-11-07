"""Chart-ready summaries of the Approach Link Table.

``summarize(link_dir, mart_dir)`` joins the links with the analysis mart
(``fact_approach.csv`` and ``bridge_approach_sector.csv`` from
:mod:`piaa.analysis.mart`) and writes ``summary/`` CSVs:

* ``headline.csv``            - counts by link type x form / strength, QC and verification
* ``approach_flags.csv``      - one row per approach: replicated / scaled flags, best strength / form
* ``by_sector.csv``           - sector-weighted rates (weights = sector shares, as in the mart)
* ``by_region.csv``, ``by_solution.csv``, ``by_period.csv``, ``by_code.csv`` - unweighted approach rates
* ``top_sources.csv``         - most cited replication sources

Only in-scope approaches (DDAT code assigned, not NONE) are counted. Each
rate is given for all links and for QC-agreed links only (``*_agreed``).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REP_ORDER = ["verified", "named", "unnamed"]
SCA_ORDER = ["additional_financing", "series", "expansion_in_project", "structural"]


def _best(vals, order):
    for o in order:
        if o in set(vals):
            return o
    return ""


def approach_flags(L: pd.DataFrame, codes: pd.DataFrame) -> pd.DataFrame:
    A = codes.copy()
    A["in_scope"] = A["approach_code"].astype(str).str.fullmatch(r"\d{6}")
    out = A[["approach_id", "project_id", "approach_code", "approach_name", "solution_code", "in_scope"]].copy()
    for suffix, sub in (("", L), ("_agreed", L[L["review_status"] == "agreed"])):
        rep = sub[sub.link_type == "replication"].groupby("target_row_id")["form_or_strength"].agg(lambda v: _best(v, REP_ORDER))
        sca = sub[sub.link_type == "scaling"].groupby("target_row_id")["form_or_strength"].agg(lambda v: _best(v, SCA_ORDER))
        out["replication" + suffix] = out.approach_id.map(rep).fillna("")
        out["scaling" + suffix] = out.approach_id.map(sca).fillna("")
        out["replicated" + suffix] = out["replication" + suffix] != ""
        out["scaled" + suffix] = out["scaling" + suffix] != ""
        out["replicated_named" + suffix] = out["replication" + suffix].isin(["verified", "named"])
        out["scaled_cue" + suffix] = out["scaling" + suffix].isin(["additional_financing", "series", "expansion_in_project"])
    return out


def _rates(df, by, w=None):
    cols = ["replicated", "replicated_named", "scaled", "scaled_cue", "replicated_agreed", "scaled_agreed"]
    d = df.copy()
    d["_w"] = d[w] if w else 1.0
    g = d.groupby(by)
    res = pd.DataFrame({"approaches": g["_w"].sum()})
    for c in cols:
        res[c + "_share"] = g.apply(lambda x: (x[c] * x["_w"]).sum() / x["_w"].sum() if x["_w"].sum() else 0)
    res["n_rows"] = g.size()
    return res.reset_index().sort_values("approaches", ascending=False)


def summarize(link_dir, mart_dir) -> Path:
    link_dir, mart_dir = Path(link_dir), Path(mart_dir)
    out = link_dir / "summary"
    out.mkdir(exist_ok=True)
    L = pd.read_csv(link_dir / "approach_link_table.csv", dtype={"approach_code": str})
    codes = pd.read_csv(link_dir / "approach_codes.csv", dtype={"approach_code": str})
    L = L[L["in_scope"].astype(str) == "True"]
    F = approach_flags(L, codes)
    fa = pd.read_csv(mart_dir / "fact_approach.csv")
    keep = ["approach_id", "region_group", "pillar_code", "fy_period", "lead_major_sector", "country", "project_name"]
    F = F.merge(fa[[c for c in keep if c in fa.columns]], on="approach_id", how="left")
    F.to_csv(out / "approach_flags.csv", index=False)
    S = F[F.in_scope]

    h = L.groupby(["link_type", "form_or_strength"]).agg(links=("link_id", "size"), approaches=("target_row_id", "nunique"),
                                                         projects=("target_project_id", "nunique")).reset_index()
    h["agreed_links"] = h.apply(lambda r: ((L.link_type == r.link_type) & (L.form_or_strength == r.form_or_strength) &
                                           (L.review_status == "agreed")).sum(), axis=1)
    h.to_csv(out / "headline.csv", index=False)

    B = pd.read_csv(mart_dir / "bridge_approach_sector.csv")[["approach_id", "major_sector", "sector_share"]]
    SB = S.merge(B, on="approach_id", how="left")
    SB["sector_share"] = SB["sector_share"].fillna(1.0)
    SB["major_sector"] = SB["major_sector"].fillna("Unspecified")
    _rates(SB, "major_sector", "sector_share").to_csv(out / "by_sector.csv", index=False)
    _rates(S, "region_group").to_csv(out / "by_region.csv", index=False)
    _rates(S, "solution_code").to_csv(out / "by_solution.csv", index=False)
    _rates(S, "fy_period").to_csv(out / "by_period.csv", index=False)
    _rates(S, ["approach_code", "approach_name"]).to_csv(out / "by_code.csv", index=False)

    R = L[(L.link_type == "replication") & (L.source_text.notna())]
    top = R.groupby(R.source_project_id.fillna(R.source_text.str[:80])).agg(
        links=("link_id", "size"), targets=("target_project_id", "nunique"),
        in_portfolio=("source_in_portfolio", "first"), example=("source_text", "first")).reset_index().sort_values("links", ascending=False)
    top.to_csv(out / "top_sources.csv", index=False)

    proj = S.groupby("project_id").agg(rep=("replicated", "any"), sca=("scaled", "any"), rep_n=("replicated_named", "any"),
                                       sca_c=("scaled_cue", "any"))
    kp = {
        "in_scope_approaches": int(len(S)), "projects": int(S.project_id.nunique()),
        "approaches_replicated": int(S.replicated.sum()), "approaches_replicated_named_or_verified": int(S.replicated_named.sum()),
        "approaches_scaled": int(S.scaled.sum()), "approaches_scaled_cue_based": int(S.scaled_cue.sum()),
        "approaches_replicated_agreed": int(S.replicated_agreed.sum()), "approaches_scaled_agreed": int(S.scaled_agreed.sum()),
        "projects_with_replication": int(proj.rep.sum()), "projects_with_scaling": int(proj.sca.sum()),
        "links": int(len(L)), "links_flagged": int((L.review_status == "flagged").sum()),
        "replication_same_country_share": float((L[(L.link_type == "replication") & (L.same_country.astype(str) != "unknown")]
                                                 .same_country.astype(str) == "True").mean() or 0),
        "verification_passed": int((L.verification == "passed").sum()), "verification_failed": int((L.verification == "failed").sum()),
    }
    pd.Series(kp).to_csv(out / "kpis.csv", header=["value"])
    return out
