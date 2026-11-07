"""Chart-ready aggregates computed from a mart folder (see ``mart.py``).

Every function returns a tidy DataFrame; ``write_aggregates`` writes them all to
``<mart folder>/aggregates/*.csv``.  Definitions:

* DEFAULT sector view = ``sector_summary``: commitment-weighted. Each approach counts in a sector
  with ``commitment x sector share`` (see mart.py). ``sector_summary_count`` is the older
  share-only view, kept for projects without a commitment amount.

* project-equivalents (``proj_eq``)  = sum of sector shares (or theme intensities) over projects
* ``approaches_w``                    = sector-weighted (or theme-weighted) approach count
* ``approaches_per_project``          = approaches_w / proj_eq  ("innovation intensity")
* ``lift_vs_projects``                = share of approaches / share of project-equivalents (1.0 = proportional)
* ``lift_vs_commitment``              = share of approaches / share of portfolio commitment
* ``ai_share``                        = share of approaches coded to pillar P4 (AI Readiness & Adaptation)

Only projects that were analysed (review status generated / reviewed / pushed) enter the denominators.
Commitment-based measures only cover projects with a commitment amount.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

AI = "P4"


def _load(folder: Path) -> dict[str, pd.DataFrame]:
    return {n: pd.read_csv(folder / f"{n}.csv") for n in
            ("dim_project", "project_sector", "project_theme", "fact_approach",
             "bridge_approach_sector", "bridge_approach_theme")}


def kpis(t) -> pd.DataFrame:
    D, F = t["dim_project"], t["fact_approach"]
    an = D[D["analysed"]]
    return pd.DataFrame([{
        "projects_in_list": len(D), "projects_analysed": len(an),
        "projects_with_approach": int(an["has_approach"].sum()),
        "pct_projects_with_approach": an["has_approach"].mean(),
        "approaches": len(F), "approaches_per_project": len(F) / len(an),
        "ai_approaches": int((F["pillar_code"] == AI).sum()), "ai_share": (F["pillar_code"] == AI).mean(),
        "commitment_usd_bn": an["commitment_usd"].sum() / 1e9,
        "projects_missing_commitment": int(an["commitment_usd"].isna().sum()),
        "approaches_no_clear_digital": int((F["tech_archetype"] == "No clear digital element").sum()),
        "approaches_not_mapped": int((F["solution_code"] == "NONE").sum()),
        "pillar_overridden_by_solution": int((F["mapping_status"] == "pillar_overridden_by_solution").sum()),
    }])


def pillar_solution(t) -> pd.DataFrame:
    F = t["fact_approach"]
    g = F.groupby(["pillar_code", "pillar", "solution_code", "solution"], as_index=False).agg(
        approaches=("approach_id", "count"), projects=("project_id", "nunique"),
        attributed_usd_m=("attributed_commitment", lambda s: s.sum() / 1e6))
    g["share"] = g["approaches"] / g["approaches"].sum()
    # Strict hierarchy check: one pillar per solution.
    multi = g.groupby("solution_code")["pillar_code"].nunique()
    assert (multi <= 1).all(), f"solution mapped to several pillars: {list(multi[multi > 1].index)}"
    return g.sort_values("approaches", ascending=False)


def mapping_review(t) -> pd.DataFrame:
    """Approaches whose model-assigned pillar disagreed with their solution, or that have no solution."""
    F = t["fact_approach"]
    r = F[F["mapping_status"] != "consistent"]
    return r[["approach_id", "project_id", "project_name", "mapping_status", "pillar_code_raw", "solution_code",
              "pillar_code", "approach", "tech_archetype"]].sort_values(["mapping_status", "approach_id"])


def _proj_sector(t) -> pd.DataFrame:
    D = t["dim_project"]
    an = D[D["analysed"]][["project_id", "commitment_usd", "has_approach"]]
    ps = t["project_sector"].merge(an, on="project_id")
    ps["w_usd"] = ps["commitment_usd"].fillna(0) * ps["sector_share"]
    ps["w_with"] = ps["sector_share"] * ps["has_approach"]
    return ps


def sector_summary(t) -> pd.DataFrame:
    """Commitment-weighted sector view (default).

    usd_weighted_approaches = sum over approach x sector rows of commitment x sector share.
    portfolio_usd           = sum over projects of commitment x sector share (the sector's lending).
    lift                    = share of usd-weighted approaches / share of portfolio commitment
                              (1.0 = the sector's approaches are proportional to its lending).
    Projects without a commitment amount contribute 0; ``coverage`` columns report that.
    """
    ps, B = _proj_sector(t), t["bridge_approach_sector"]
    g = ps.groupby("major_sector").agg(projects=("project_id", "nunique"), portfolio_usd=("w_usd", "sum"))
    g["projects_with_commitment"] = ps[ps["commitment_usd"].notna()].groupby("major_sector")["project_id"].nunique()
    b = B.groupby("major_sector").agg(usd_weighted_approaches=("commitment_weight", "sum"),
                                      approaches_count_w=("weighted_count", "sum"),
                                      attributed_usd=("attributed_commitment", "sum"))
    ai = B[B["pillar_code"] == AI].groupby("major_sector")["commitment_weight"].sum().rename("ai_usd_weighted_approaches")
    s = g.join(b).join(ai).fillna(0)
    s["share_of_usd_weighted_approaches"] = s["usd_weighted_approaches"] / s["usd_weighted_approaches"].sum()
    s["share_of_commitment"] = s["portfolio_usd"] / s["portfolio_usd"].sum()
    s["share_of_approaches_count"] = s["approaches_count_w"] / s["approaches_count_w"].sum()
    s["lift_vs_commitment"] = s["share_of_usd_weighted_approaches"] / s["share_of_commitment"]
    s["approaches_per_100m_usd"] = s["approaches_count_w"] / (s["portfolio_usd"] / 1e8)
    s["ai_share"] = s["ai_usd_weighted_approaches"] / s["usd_weighted_approaches"]
    s["share_of_ai_usd_weighted"] = s["ai_usd_weighted_approaches"] / s["ai_usd_weighted_approaches"].sum()
    for c in ("usd_weighted_approaches", "ai_usd_weighted_approaches", "portfolio_usd", "attributed_usd"):
        s[c.replace("_usd", "_usd_bn") if c.endswith("_usd") else c + "_bn"] = s[c] / 1e9
    s = s.drop(columns=["usd_weighted_approaches", "ai_usd_weighted_approaches", "portfolio_usd", "attributed_usd"]).reset_index()
    return s[s["major_sector"] != "Unspecified"].sort_values("usd_weighted_approaches_bn", ascending=False)


def sector_summary_count(t) -> pd.DataFrame:
    """Share-only sector view (no commitment): sector-share-weighted approach counts."""
    ps, B = _proj_sector(t), t["bridge_approach_sector"]
    g = ps.groupby("major_sector").agg(projects=("project_id", "nunique"), proj_eq=("sector_share", "sum"),
                                       proj_eq_with_approach=("w_with", "sum"))
    b = B.groupby("major_sector").agg(approaches_w=("weighted_count", "sum"))
    ai = B[B["pillar_code"] == AI].groupby("major_sector")["weighted_count"].sum().rename("ai_approaches_w")
    s = g.join(b).join(ai).fillna(0)
    s["share_of_projects"] = s["proj_eq"] / s["proj_eq"].sum()
    s["share_of_approaches"] = s["approaches_w"] / s["approaches_w"].sum()
    s["lift_vs_projects"] = s["share_of_approaches"] / s["share_of_projects"]
    s["approaches_per_project"] = s["approaches_w"] / s["proj_eq"]
    s["pct_projects_with_approach"] = s["proj_eq_with_approach"] / s["proj_eq"]
    s["ai_share"] = s["ai_approaches_w"] / s["approaches_w"]
    s = s.reset_index()
    return s[s["major_sector"] != "Unspecified"].sort_values("approaches_w", ascending=False)


def sector_solution(t) -> pd.DataFrame:
    B = t["bridge_approach_sector"]
    g = B.groupby(["major_sector", "solution_code", "solution"], as_index=False).agg(
        approaches_w=("weighted_count", "sum"), usd_weighted_approaches_bn=("commitment_weight", lambda s: s.sum() / 1e9),
        attributed_usd_m=("attributed_commitment", lambda s: s.sum() / 1e6))
    g["share_within_sector"] = g["usd_weighted_approaches_bn"] / g.groupby("major_sector")["usd_weighted_approaches_bn"].transform("sum")
    g["share_within_sector_count"] = g["approaches_w"] / g.groupby("major_sector")["approaches_w"].transform("sum")
    return g[g["major_sector"] != "Unspecified"]


def sector_archetype(t) -> pd.DataFrame:
    B = t["bridge_approach_sector"]
    g = B.groupby(["major_sector", "tech_archetype"], as_index=False).agg(approaches_w=("weighted_count", "sum"))
    g["share_within_sector"] = g["approaches_w"] / g.groupby("major_sector")["approaches_w"].transform("sum")
    return g[g["major_sector"] != "Unspecified"]


def theme_summary(t) -> pd.DataFrame:
    """Theme groups. Intensity per project = max pct over its level-2 themes in the group."""
    D = t["dim_project"]
    an = D[D["analysed"]][["project_id", "n_approaches", "commitment_usd"]]
    pt = t["project_theme"].groupby(["project_id", "theme_group"], as_index=False)["theme_pct"].max()
    pt = pt.merge(an, on="project_id")
    pt["w"] = pt["theme_pct"] / 100
    pt["appr_w"] = pt["w"] * pt["n_approaches"]
    g = pt.groupby("theme_group").agg(projects_tagged=("project_id", "nunique"), proj_eq=("w", "sum"),
                                      approaches_w=("appr_w", "sum"))
    bt = t["bridge_approach_theme"].groupby(["approach_id", "theme_group", "pillar_code"], as_index=False)["theme_intensity"].max()
    ai = bt[bt["pillar_code"] == AI].groupby("theme_group")["theme_intensity"].sum().rename("ai_approaches_w")
    g = g.join(ai).fillna(0)
    g["approaches_per_project"] = g["approaches_w"] / g["proj_eq"]
    g["ai_share"] = g["ai_approaches_w"] / g["approaches_w"]
    return g.reset_index().sort_values("approaches_w", ascending=False)


def theme_solution(t) -> pd.DataFrame:
    bt = t["bridge_approach_theme"].groupby(["approach_id", "theme_group", "solution_code"], as_index=False)["theme_intensity"].max()
    g = bt.groupby(["theme_group", "solution_code"], as_index=False).agg(approaches_w=("theme_intensity", "sum"))
    g["share_within_theme"] = g["approaches_w"] / g.groupby("theme_group")["approaches_w"].transform("sum")
    return g


def region_summary(t) -> pd.DataFrame:
    D, F = t["dim_project"], t["fact_approach"]
    an = D[D["analysed"]]
    g = an.groupby("region_group").agg(projects=("project_id", "count"), with_approach=("has_approach", "sum"),
                                       commitment_usd_m=("commitment_usd", lambda s: s.sum() / 1e6),
                                       approaches=("n_approaches", "sum"))
    ai = F[F["pillar_code"] == AI].groupby("region_group").size().rename("ai_approaches")
    g = g.join(ai).fillna(0)
    g["approaches_per_project"] = g["approaches"] / g["projects"]
    g["ai_share"] = g["ai_approaches"] / g["approaches"]
    return g.reset_index().sort_values("approaches", ascending=False)


def region_solution(t) -> pd.DataFrame:
    F = t["fact_approach"]
    g = F.groupby(["region_group", "solution_code"], as_index=False).agg(approaches=("approach_id", "count"))
    g["share_within_region"] = g["approaches"] / g.groupby("region_group")["approaches"].transform("sum")
    return g


def fy_trend(t) -> pd.DataFrame:
    D, F = t["dim_project"], t["fact_approach"]
    an = D[D["analysed"] & D["approval_fy"].notna()]
    g = an.groupby("approval_fy").agg(projects=("project_id", "count"), approaches=("n_approaches", "sum"))
    ai = F[F["pillar_code"] == AI].groupby("approval_fy").size().rename("ai_approaches")
    g = g.join(ai).fillna(0)
    g["approaches_per_project"] = g["approaches"] / g["projects"]
    g["ai_share"] = g["ai_approaches"] / g["approaches"]
    g = g.reset_index()
    g["approval_fy"] = g["approval_fy"].astype(int)
    return g


def period_trend(t) -> pd.DataFrame:
    D, F = t["dim_project"], t["fact_approach"]
    an = D[D["analysed"] & (D["fy_period"] != "n/a")]
    g = an.groupby("fy_period").agg(projects=("project_id", "count"), approaches=("n_approaches", "sum"))
    ai = F[F["pillar_code"] == AI].groupby("fy_period").size().rename("ai_approaches")
    g = g.join(ai).fillna(0)
    g["approaches_per_project"] = g["approaches"] / g["projects"]
    g["ai_share"] = g["ai_approaches"] / g["approaches"]
    return g.reset_index()


def archetype_summary(t) -> pd.DataFrame:
    F = t["fact_approach"]
    g = F.groupby("tech_archetype", as_index=False).agg(approaches=("approach_id", "count"),
                                                         projects=("project_id", "nunique"))
    g["share"] = g["approaches"] / g["approaches"].sum()
    return g.sort_values("approaches", ascending=False)


def size_summary(t) -> pd.DataFrame:
    D = t["dim_project"]
    an = D[D["analysed"]]
    g = an.groupby("size_band").agg(projects=("project_id", "count"), approaches=("n_approaches", "sum"),
                                    pct_with_approach=("has_approach", "mean"))
    g["approaches_per_project"] = g["approaches"] / g["projects"]
    return g.reset_index()


def stage_summary(t) -> pd.DataFrame:
    F = t["fact_approach"]
    return F.groupby(["evidence_stage", "pillar_code"], as_index=False).agg(approaches=("approach_id", "count"))


def ai_approaches(t) -> pd.DataFrame:
    F = t["fact_approach"]
    a = F[F["pillar_code"] == AI][["approach_id", "project_id", "project_name", "region_group", "lead_major_sector",
                                   "approval_fy", "approach", "tech_archetype"]]
    return a.sort_values(["lead_major_sector", "project_id"])


ALL = {"kpis": kpis, "pillar_solution": pillar_solution, "sector_summary": sector_summary,
       "sector_summary_count": sector_summary_count, "sector_solution": sector_solution, "sector_archetype": sector_archetype, "theme_summary": theme_summary,
       "theme_solution": theme_solution, "region_summary": region_summary, "region_solution": region_solution,
       "fy_trend": fy_trend, "period_trend": period_trend, "archetype_summary": archetype_summary,
       "size_summary": size_summary, "stage_summary": stage_summary, "ai_approaches": ai_approaches,
       "mapping_review": mapping_review}


def write_aggregates(mart_folder: str | Path) -> Path:
    folder = Path(mart_folder)
    t = _load(folder)
    out = folder / "aggregates"
    out.mkdir(exist_ok=True)
    for name, fn in ALL.items():
        fn(t).to_csv(out / f"{name}.csv", index=False)
    return out
