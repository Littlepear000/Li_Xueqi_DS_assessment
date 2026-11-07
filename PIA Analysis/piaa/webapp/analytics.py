"""Analytics for the web app's Analytics tab.

Builds the six chart blocks agreed for the analysis deck from the *current* state of the
review database (manual edits included), whatever workflow produced it:

  kpis            - headline tiles
  sector_count    - approaches per major sector (no year)
  sector_fy       - approaches per major sector x approval FY
  ai_by_sector    - AI share of each sector's commitment-weighted approaches
  category_fy     - approaches per category x approval FY (category = whatever the current workflow stores)
  theme_count / theme_fy - approaches per harmonised theme group, and by FY
  sector_category - approaches per major sector x category

Rules
-----
* Projects counted = review status generated / reviewed / pushed.  Approaches counted =
  status not in (rejected, mentioned_only).
* The approach's own matched sector / theme is used; when the workflow left it empty the
  project's largest coded sector / theme is used instead.
* AI = solution S9 where a solution code exists, otherwise a keyword rule on the approach
  text (shown on the page as such).
* Commitment weight per approach-sector row = project commitment x sector share
  (sectors_json); projects without a commitment carry zero weight in the AI chart only.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from ..analysis.crosswalks import major_sector, region_group, theme_group

AI_RE = re.compile(r"\bai\b|artificial intelligence|machine learning|\bml\b|predictive|deep learning|neural|computer vision|"
                   r"natural language|large language|chatbot|algorithm", re.I)
LIVE_REVIEW = ("generated", "reviewed", "pushed")
DEAD_STATUS = ("rejected", "mentioned_only")
FY_MIN, FY_MAX = 2019, 2026


def _shares(sectors_json: str) -> list[tuple[str, float]]:
    secs = json.loads(sectors_json or "[]")
    tot = sum(float(s.get("pct") or 0) for s in secs)
    if not secs:
        return []
    if tot <= 0:
        return [(s["name"], 1.0 / len(secs)) for s in secs]
    return [(s["name"], float(s.get("pct") or 0) / tot) for s in secs if float(s.get("pct") or 0) > 0]


def _theme_group_of(theme: str) -> str:
    if not theme or theme == "none":
        return ""
    l1, _, l2 = theme.partition(" > ")
    return theme_group(l1, l2)


def _is_ai(a: dict) -> bool:
    if (a.get("category_solution_code") or "").upper() == "S9":
        return True
    return bool(AI_RE.search(" ".join(str(a.get(k) or "") for k in ("name", "description", "why_innovative"))))


def compute(c) -> dict:
    """``c`` is an open sqlite3 connection with row_factory = sqlite3.Row."""
    projects = {r["project_id"]: dict(r) for r in c.execute(
        "SELECT p.*, r.status AS review_status, r.innovative FROM projects p LEFT JOIN review r USING(project_id)")}
    latest_tag = {r["project_id"]: r["workflow_tag"] or r["workflow"] for r in c.execute(
        "SELECT project_id, workflow, workflow_tag FROM runs ORDER BY started_at")}  # last row wins
    analysed = {pid: p for pid, p in projects.items() if (p.get("review_status") or "") in LIVE_REVIEW}
    aps = [dict(r) for r in c.execute("SELECT * FROM approaches") if r["status"] not in DEAD_STATUS and r["project_id"] in analysed]

    # per-project helpers
    shares = {pid: _shares(p.get("sectors_json")) for pid, p in analysed.items()}
    top_sector = {pid: (max(s, key=lambda x: x[1])[0] if s else "") for pid, s in shares.items()}
    top_theme = {}
    for pid, p in analysed.items():
        th = json.loads(p.get("themes_json") or "[]")
        top_theme[pid] = max(th, key=lambda t: float(t.get("pct") or 0))["name"] if th else ""

    for a in aps:
        pid = a["project_id"]
        sec = a.get("sector") or ""
        a["_sector"] = sec if sec and sec != "none" else top_sector.get(pid, "")
        a["_major"] = major_sector(a["_sector"]) if a["_sector"] else "Unspecified"
        th = a.get("theme") or ""
        a["_theme"] = th if th and th != "none" else top_theme.get(pid, "")
        a["_tgroup"] = _theme_group_of(a["_theme"]) or "Unspecified"
        a["_fy"] = analysed[pid].get("approval_fy")
        a["_cat"] = a.get("category") or "Unassigned"
        a["_ai"] = _is_ai(a)

    fys = list(range(FY_MIN, FY_MAX + 1))
    fy_labels = [f"FY{str(y)[2:]}" for y in fys]

    def crosstab(row_key, col_key, rows=None):
        tab = defaultdict(Counter)
        for a in aps:
            tab[row_key(a)][col_key(a)] += 1
        return tab

    # ---- sector count
    sec_counter = Counter(a["_major"] for a in aps if a["_major"] != "Unspecified")
    sector_labels = [k for k, _ in sec_counter.most_common()]
    sector_count = {"labels": sector_labels, "values": [sec_counter[k] for k in sector_labels]}

    # ---- sector x FY (top 6 + other)
    tab = crosstab(lambda a: a["_major"], lambda a: a["_fy"])
    top6 = [s for s in sector_labels[:6]]
    series = [{"name": s, "values": [tab[s].get(y, 0) for y in fys]} for s in top6]
    other = [sum(tab[s].get(y, 0) for s in tab if s not in top6 and s != "Unspecified") for y in fys]
    sector_fy = {"labels": fy_labels, "series": series + [{"name": "Other sectors", "values": other}]}

    # ---- AI by sector (commitment weighted) + count-based fallback
    w_all, w_ai, n_all, n_ai = Counter(), Counter(), Counter(), Counter()
    for a in aps:
        commit = analysed[a["project_id"]].get("commitment_usd") or 0
        for name, sh in shares[a["project_id"]] or [(a["_sector"], 1.0)]:
            m = major_sector(name)
            w_all[m] += commit * sh
            n_all[m] += sh
            if a["_ai"]:
                w_ai[m] += commit * sh
                n_ai[m] += sh
    ai_labels = [s for s in sector_labels if s in w_all]
    ai_by_sector = {"labels": ai_labels,
                    "ai_share_usd": [round(100 * w_ai[s] / w_all[s], 1) if w_all[s] else 0 for s in ai_labels],
                    "ai_share_count": [round(100 * n_ai[s] / n_all[s], 1) if n_all[s] else 0 for s in ai_labels],
                    "share_of_all_ai_usd": [round(100 * w_ai[s] / sum(w_ai.values()), 1) if sum(w_ai.values()) else 0 for s in ai_labels]}

    # ---- category x FY
    cat_counter = Counter(a["_cat"] for a in aps)
    cat_labels = [k for k, _ in cat_counter.most_common()]
    tab = crosstab(lambda a: a["_cat"], lambda a: a["_fy"])
    category_fy = {"labels": fy_labels, "series": [{"name": k, "values": [tab[k].get(y, 0) for y in fys]} for k in cat_labels],
                   "totals": {k: cat_counter[k] for k in cat_labels}}
    ai_fy = Counter(a["_fy"] for a in aps if a["_ai"])
    all_fy = Counter(a["_fy"] for a in aps)
    ai_share_fy = [round(100 * ai_fy.get(y, 0) / all_fy[y], 1) if all_fy.get(y) else 0 for y in fys]

    # ---- themes
    th_counter = Counter(a["_tgroup"] for a in aps if a["_tgroup"] != "Unspecified")
    th_labels = [k for k, _ in th_counter.most_common()]
    theme_count = {"labels": th_labels, "values": [th_counter[k] for k in th_labels]}
    tab = crosstab(lambda a: a["_tgroup"], lambda a: a["_fy"])
    top6t = th_labels[:6]
    theme_fy = {"labels": fy_labels, "series": [{"name": k, "values": [tab[k].get(y, 0) for y in fys]} for k in top6t] +
                [{"name": "Other groups", "values": [sum(tab[k].get(y, 0) for k in tab if k not in top6t and k != "Unspecified") for y in fys]}]}

    # ---- sector x category
    tab = crosstab(lambda a: a["_major"], lambda a: a["_cat"])
    sector_category = {"labels": sector_labels, "series": [{"name": k, "values": [tab[s].get(k, 0) for s in sector_labels]} for k in cat_labels]}

    # ---- KPIs
    with_ap = len({a["project_id"] for a in aps})
    commit_known = [p for p in analysed.values() if p.get("commitment_usd")]
    fy_in = [a for a in aps if a["_fy"] and FY_MIN <= a["_fy"] <= FY_MAX]
    early = [a for a in fy_in if a["_fy"] <= 2021]
    late = [a for a in fy_in if a["_fy"] >= 2022]
    tags = Counter(latest_tag.get(pid, "?") for pid in analysed)
    kpis = {
        "projects_listed": len(projects), "projects_analysed": len(analysed), "projects_with_approach": with_ap,
        "approaches": len(aps), "per_project": round(len(aps) / len(analysed), 2) if analysed else 0,
        "ai_approaches": sum(a["_ai"] for a in aps), "ai_share": round(100 * sum(a["_ai"] for a in aps) / len(aps), 1) if aps else 0,
        "sectors_reached": len(sector_labels), "sectors_total": 11,
        "commitment_bn": round(sum(p["commitment_usd"] for p in commit_known) / 1e9, 2), "projects_missing_commitment": len(analysed) - len(commit_known),
        "ai_share_early": round(100 * sum(a["_ai"] for a in early) / len(early), 1) if early else 0,
        "ai_share_late": round(100 * sum(a["_ai"] for a in late) / len(late), 1) if late else 0,
        "workflow_mix": dict(tags.most_common()),
        "ai_rule": "solution S9, or AI / machine learning / predictive keywords in the approach text",
    }
    # ---- slim per-approach records: the page aggregates these itself for any dimension / cross-tab
    records = []
    for a in aps:
        p = analysed[a["project_id"]]
        records.append({"id": a["approach_id"], "project_id": a["project_id"], "name": a.get("name") or "", "fy": a["_fy"],
                        "sector": a["_major"], "theme": a["_tgroup"], "category": a["_cat"], "solution": a.get("category_solution") or "",
                        "region": region_group(p.get("region") or ""), "vertical": p.get("vertical") or "Unspecified",
                        "practice": p.get("lead_practice") or "Unspecified", "ai": bool(a["_ai"]),
                        "commitment": float(p.get("commitment_usd") or 0),
                        "sector_weights": [[major_sector(n), round(sh, 4)] for n, sh in (shares[a["project_id"]] or [(a["_sector"], 1.0)])]})
    dims = {"sector": "Sector", "theme": "Theme", "category": "Category", "region": "Region", "vertical": "Vertical", "practice": "Lead practice"}
    return {"kpis": kpis, "dims": dims, "fy_labels": fy_labels, "fy_min": FY_MIN, "fy_max": FY_MAX, "records": records,
            "sector_count": sector_count, "sector_fy": sector_fy, "ai_by_sector": ai_by_sector,
            "category_fy": category_fy, "ai_share_fy": {"labels": fy_labels, "values": ai_share_fy},
            "theme_count": theme_count, "theme_fy": theme_fy, "sector_category": sector_category}
