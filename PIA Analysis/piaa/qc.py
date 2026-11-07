"""Quality control: compare two runs of the same workflow (Methodology Note 1).

Rows of the Approach Evidence Corpus are matched on
``(project_id, doc_id, sentence_position, approach_code)``. A row is flagged when

* it appears in only one run (``one_run_only``),
* the evidence level differs (``level_differs``),
* one run excluded the sentence (it is in that run's exclusion log) while the
  other kept a match for it (``excluded_vs_kept``).

Agreed rows are accepted; a random 5% of them is also sent to review
(``spot_check``). Agreement is reported per approach so that approaches below
80% can get their keywords or prompt revised in the next workflow version.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

KEY = ["project_id", "doc_id", "sentence_position", "approach_code"]


def _load_cache(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, excl = [], []
    for p in sorted((folder / "cache" / "projects").glob("P*.json")):
        if p.name.count(".") > 1:  # skip <P>.<run>.llm.json debug logs
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        rows += d.get("aec_rows", [])
        excl += [{"project_id": d["project_id"], "doc_id": e.get("guid"), "sentence_position": e.get("position"), **e} for e in d.get("exclusion_log", [])]
    return pd.DataFrame(rows), pd.DataFrame(excl)


def compare(run_a: Path, run_b: Path, out_dir: Path, spot_check_share: float = 0.05, seed: int = 7) -> dict:
    """Compare the cached records of two output folders and write the QC tables."""
    run_a, run_b, out_dir = Path(run_a), Path(run_b), Path(out_dir)
    a, ea = _load_cache(run_a)
    b, eb = _load_cache(run_b)
    if a.empty or b.empty:
        raise ValueError("one of the runs has no AEC rows")
    a["_run"], b["_run"] = "A", "B"
    m = a.merge(b, on=KEY, how="outer", suffixes=("_a", "_b"), indicator=True)
    sent_key = ["project_id", "doc_id", "sentence_position"]
    exa = set(map(tuple, ea[sent_key].values)) if not ea.empty else set()
    exb = set(map(tuple, eb[sent_key].values)) if not eb.empty else set()

    def flag(r):
        if r["_merge"] == "left_only":
            return "excluded_vs_kept" if tuple(r[k] for k in sent_key) in exb else "one_run_only"
        if r["_merge"] == "right_only":
            return "excluded_vs_kept" if tuple(r[k] for k in sent_key) in exa else "one_run_only"
        if r["evidence_level_a"] != r["evidence_level_b"]:
            return "level_differs"
        return "agreed"

    m["qc_flag"] = m.apply(flag, axis=1)
    m["in_run"] = m["_merge"].map({"left_only": "A", "right_only": "B", "both": "AB"})
    rng = random.Random(seed)
    agreed_idx = m.index[m["qc_flag"] == "agreed"].tolist()
    spot = set(rng.sample(agreed_idx, max(1, int(len(agreed_idx) * spot_check_share)))) if agreed_idx else set()
    m["review_status"] = ["spot_check" if i in spot else ("agreed" if f == "agreed" else "flagged") for i, f in zip(m.index, m["qc_flag"])]
    # tidy columns
    def pick(col):
        return m[f"{col}_a"].where(m[f"{col}_a"].notna(), m.get(f"{col}_b"))
    out = pd.DataFrame({k: m[k] for k in KEY})
    for col in ("approach_name", "doc_type", "doc_date", "sentence", "reason", "status", "solution", "pillar", "match_route"):
        if f"{col}_a" in m:
            out[col] = pick(col)
    out["evidence_level_a"] = m.get("evidence_level_a")
    out["evidence_level_b"] = m.get("evidence_level_b")
    out["reason_b"] = m.get("reason_b")
    out["in_run"], out["qc_flag"], out["review_status"] = m["in_run"], m["qc_flag"], m["review_status"]
    out = out.sort_values(["project_id", "doc_id", "sentence_position", "approach_code"]).reset_index(drop=True)
    # agreement per approach: agreed / (rows in A ∪ B)
    per = out.groupby("approach_code").agg(rows=("qc_flag", "size"), agreed=("qc_flag", lambda s: (s == "agreed").sum()),
                                           level_differs=("qc_flag", lambda s: (s == "level_differs").sum()),
                                           one_run_only=("qc_flag", lambda s: (s == "one_run_only").sum()),
                                           excluded_vs_kept=("qc_flag", lambda s: (s == "excluded_vs_kept").sum())).reset_index()
    per["agreement"] = (per["agreed"] / per["rows"]).round(3)
    per["needs_revision"] = per["agreement"] < 0.8
    names = out.drop_duplicates("approach_code").set_index("approach_code")["approach_name"]
    per.insert(1, "approach_name", per["approach_code"].map(names))
    # project-level agreement: same set of headline approach codes?
    def headline(df):
        return df[df["evidence_level"].isin(["L2", "L3"])].groupby("project_id")["approach_code"].apply(lambda s: frozenset(s))
    ha, hb = headline(a), headline(b)
    proj = pd.DataFrame({"codes_a": ha, "codes_b": hb})
    proj["codes_a"] = proj["codes_a"].apply(lambda x: x if isinstance(x, frozenset) else frozenset())
    proj["codes_b"] = proj["codes_b"].apply(lambda x: x if isinstance(x, frozenset) else frozenset())
    proj["same_headline_set"] = proj["codes_a"] == proj["codes_b"]
    proj["only_a"] = [";".join(sorted(x - y)) for x, y in zip(proj["codes_a"], proj["codes_b"])]
    proj["only_b"] = [";".join(sorted(y - x)) for x, y in zip(proj["codes_a"], proj["codes_b"])]
    proj = proj.drop(columns=["codes_a", "codes_b"]).reset_index().rename(columns={"index": "project_id"})
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / "qc_rows.csv", index=False)
    per.to_csv(out_dir / "qc_agreement_by_approach.csv", index=False)
    proj.to_csv(out_dir / "qc_project_headline.csv", index=False)
    summary = {
        "rows_a": int(len(a)), "rows_b": int(len(b)), "rows_union": int(len(out)),
        "agreed": int((out["qc_flag"] == "agreed").sum()), "flagged": int((out["qc_flag"] != "agreed").sum()),
        "flags": out["qc_flag"].value_counts().to_dict(), "spot_check": int((out["review_status"] == "spot_check").sum()),
        "row_agreement": round(float((out["qc_flag"] == "agreed").mean()), 3),
        "projects_same_headline_set": int(proj["same_headline_set"].sum()), "projects": int(len(proj)),
        "approaches_below_80": per.loc[per["needs_revision"], "approach_code"].tolist(),
        "files": {k: str(out_dir / f) for k, f in {"rows": "qc_rows.csv", "by_approach": "qc_agreement_by_approach.csv", "by_project": "qc_project_headline.csv"}.items()},
    }
    (out_dir / "qc_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
