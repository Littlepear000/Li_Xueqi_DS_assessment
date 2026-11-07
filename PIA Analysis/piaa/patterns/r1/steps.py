"""Pattern workflow r1: replication by matching name + evidence + theme; provisional scaling."""
from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict

from ...analysis.crosswalks import major_sector, region_group
from .. import PatternContext

STOP = set("""a an and are as at be by for from has have in into is it its of on or that the their this to was were will with
within which using use used through based new project projects support system systems""".split())


def run(ctx: PatternContext) -> None:
    for name in ctx.cfg("steps", []):
        globals()[f"step_{name}"](ctx)


# ----------------------------------------------------------------------------- helpers
def _tokens(text: str, ngram_max: int) -> list[str]:
    words = [w for w in re.findall(r"[a-z][a-z0-9\-]+", (text or "").lower()) if w not in STOP and len(w) > 2]
    out = list(words)
    if ngram_max >= 2:
        out += [f"{a} {b}" for a, b in zip(words, words[1:])]
    return out


def _tfidf(texts: list[str], ngram_max: int = 2) -> list[dict[str, float]]:
    """Sublinear TF-IDF, L2-normalised sparse vectors (dict term -> weight)."""
    docs = [Counter(_tokens(t, ngram_max)) for t in texts]
    df = Counter(term for d in docs for term in d)
    n = len(docs)
    vecs = []
    for d in docs:
        v = {t: (1 + math.log(c)) * (math.log((1 + n) / (1 + df[t])) + 1) for t, c in d.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return vecs


def _cos(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def _theme_sim(a: str, b: str, m: dict) -> float:
    if not a or not b:
        return m.get("other", 0.0)
    if a == b:
        return m.get("same_level2", 1.0)
    if a.split(" > ")[0] == b.split(" > ")[0]:
        return m.get("same_level1", 0.5)
    return m.get("other", 0.0)


def _write_csv(path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


# ----------------------------------------------------------------------------- steps
def step_corpus(ctx: PatternContext) -> None:
    """Read validated approaches and their project metadata (read-only connection)."""
    sc = ctx.cfg("scope", {})
    ex_status, ex_adopt = set(sc.get("exclude_status", [])), set(sc.get("exclude_adoption", []))
    uri = f"file:{ctx.db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    cols = {r["name"] for r in con.execute("PRAGMA table_info(approaches)")}
    adopt_col = "a.adoption" if "adoption" in cols else "NULL"
    rows = con.execute(f"""SELECT a.approach_id, a.project_id, a.name, a.description, a.evidence_json, a.sector, a.theme,
                                  a.category, a.category_solution, a.status, {adopt_col} AS adoption,
                                  p.project_name, p.country, p.region, p.approval_date, p.approval_fy, p.commitment_usd, p.sectors_json
                           FROM approaches a JOIN projects p USING(project_id)""").fetchall()
    con.close()
    corpus = []
    for r in rows:
        if r["status"] in ex_status or (r["adoption"] or "") in ex_adopt:
            continue
        ev = json.loads(r["evidence_json"] or "{}")
        psec = sorted(json.loads(r["sectors_json"] or "[]"), key=lambda x: -(x.get("pct") or 0))
        sector = r["sector"] or (psec[0]["name"] if psec else "")
        corpus.append({
            "approach_id": r["approach_id"], "project_id": r["project_id"], "project_name": r["project_name"] or "",
            "name": r["name"] or "", "description": r["description"] or "", "evidence": ev.get("text", "") or "", "evidence_doc": f"{ev.get('doc_type', '')} {ev.get('doc_date', '')}".strip(),
            "theme": r["theme"] or "", "sector": sector, "major_sector": major_sector(sector),
            "solution": r["category_solution"] or "", "pillar": r["category"] or "",
            "country": r["country"] or "", "region": r["region"] or "", "region_short": region_group(r["region"] or ""),
            "approval_date": r["approval_date"] or "", "fy": int(r["approval_fy"]) if r["approval_fy"] else None,
            "commitment_usd": r["commitment_usd"],
        })
    corpus.sort(key=lambda a: (a["approval_date"] or "9999", a["project_id"], a["approach_id"]))
    ctx.data["corpus"] = corpus
    ctx.log("corpus", note=f"{len(corpus)} approaches in {len({a['project_id'] for a in corpus})} projects (of {len(rows)} stored)")


def step_similarity(ctx: PatternContext) -> None:
    c = ctx.cfg("similarity", {})
    w = c.get("weights", {"name": 0.4, "evidence": 0.35, "theme": 0.25})
    corpus = ctx.data["corpus"]
    vn = _tfidf([a["name"] for a in corpus], c.get("ngram_max", 2))
    ve = _tfidf([a["evidence"] for a in corpus], c.get("ngram_max", 2))
    vd = _tfidf([a["description"] for a in corpus], c.get("ngram_max", 2)) if w.get("description") else None
    thr = c.get("candidate_threshold", 0.3)
    score = {}
    pairs = []
    for i in range(len(corpus)):
        for j in range(i + 1, len(corpus)):
            a, b = corpus[i], corpus[j]
            if a["project_id"] == b["project_id"]:
                continue
            sn, se = _cos(vn[i], vn[j]), _cos(ve[i], ve[j])
            st = _theme_sim(a["theme"], b["theme"], c.get("theme_match", {}))
            sd = _cos(vd[i], vd[j]) if vd else 0.0
            s = w["name"] * sn + w["evidence"] * se + w.get("description", 0) * sd + w["theme"] * st
            if s >= thr:
                score[(i, j)] = s
                pairs.append({"a": a["approach_id"], "b": b["approach_id"], "project_a": a["project_id"], "project_b": b["project_id"],
                              "name_a": a["name"], "name_b": b["name"], "sim_name": round(sn, 3), "sim_evidence": round(se, 3), "sim_description": round(sd, 3),
                              "theme_match": st, "score": round(s, 3), "confirmed": ""})
    ctx.data["score"] = score
    ctx.data["pairs"] = pairs
    ctx.log("similarity", note=f"{len(pairs)} candidate pairs >= {thr}")


def step_confirm(ctx: PatternContext) -> None:
    c = ctx.cfg("confirm", {})
    if not c.get("enabled") or ctx.llm is None:
        ctx.log("confirm", status="skipped", note="disabled in config" if not c.get("enabled") else "no LLM client")
        return
    lo, hi = c.get("grey_zone", [0.38, 0.55])
    corpus, score = ctx.data["corpus"], ctx.data["score"]
    idx = {a["approach_id"]: i for i, a in enumerate(corpus)}
    grey = sorted([p for p in ctx.data["pairs"] if lo <= p["score"] < hi], key=lambda p: -p["score"])[: c.get("max_pairs", 200)]
    wf = ctx.workflow
    n_yes = n_no = 0
    for p in grey:
        i, j = idx[p["a"]], idx[p["b"]]
        a, b = corpus[i], corpus[j]
        prompt = wf.prompt("01_confirm", project_a=a["project_id"], fy_a=a["fy"], country_a=a["country"], name_a=a["name"], theme_a=a["theme"], evidence_a=a["evidence"][:600],
                           project_b=b["project_id"], fy_b=b["fy"], country_b=b["country"], name_b=b["name"], theme_b=b["theme"], evidence_b=b["evidence"][:600])
        try:
            ans = ctx.llm.complete_json("confirm", wf.prompts.get("00_system", ""), prompt)
        except Exception as e:  # pragma: no cover - network
            p["confirmed"] = f"error: {e}"
            continue
        same = bool(ans.get("same"))
        p["confirmed"] = "same" if same else "different"
        key = (min(i, j), max(i, j))
        if same:
            score[key] = max(score[key], hi)
            n_yes += 1
        else:
            score[key] = 0.0
            n_no += 1
    ctx.log("confirm", note=f"{len(grey)} borderline pairs: {n_yes} same, {n_no} different")


def step_cluster(ctx: PatternContext) -> None:
    c = ctx.cfg("cluster", {})
    thr, one = c.get("threshold", 0.45), c.get("one_per_project", True)
    corpus, score = ctx.data["corpus"], ctx.data["score"]
    get = lambda i, j: score.get((min(i, j), max(i, j)), 0.0)  # noqa: E731
    clusters: list[list[int]] = []
    for i, a in enumerate(corpus):  # corpus is in approval order -> first member is the origin
        best, best_s = None, 0.0
        for k, members in enumerate(clusters):
            if one and any(corpus[m]["project_id"] == a["project_id"] for m in members):
                continue
            s = sum(get(i, m) for m in members) / len(members)
            if s >= thr and s > best_s:
                best, best_s = k, s
        if best is None:
            clusters.append([i])
        else:
            clusters[best].append(i)
    min_p = c.get("min_projects", 2)
    patterns = []
    for members in clusters:
        pids = {corpus[m]["project_id"] for m in members}
        if len(pids) < min_p:
            continue
        # label = medoid (highest mean score to the other members)
        med = max(members, key=lambda m: sum(get(m, o) for o in members if o != m))
        pair_scores = [get(x, y) for k, x in enumerate(members) for y in members[k + 1:]]
        mem = [dict(corpus[m], order=k, role="origin" if k == 0 else "replication") for k, m in enumerate(members)]
        patterns.append({
            "label": corpus[med]["name"], "n_projects": len(pids), "n_approaches": len(members), "reuse": len(pids) - 1,
            "countries": sorted({x["country"] for x in mem if x["country"]}), "regions": sorted({x["region_short"] for x in mem if x["region_short"]}),
            "sectors": [s for s, _ in Counter(x["major_sector"] for x in mem).most_common()],
            "themes": [s for s, _ in Counter(x["theme"] for x in mem if x["theme"]).most_common(3)],
            "solution": Counter(x["solution"] for x in mem if x["solution"]).most_common(1)[0][0] if any(x["solution"] for x in mem) else "",
            "first_fy": mem[0]["fy"], "last_fy": mem[-1]["fy"], "origin_project": mem[0]["project_id"], "origin_country": mem[0]["country"],
            "cohesion": round(sum(pair_scores) / len(pair_scores), 3) if pair_scores else None, "members": mem,
        })
    patterns.sort(key=lambda p: (-p["n_projects"], -(p["cohesion"] or 0)))
    for k, p in enumerate(patterns, 1):
        p["pattern_id"] = f"R{k:03d}"
    ctx.data["patterns"] = patterns
    ctx.data["in_pattern"] = {m["approach_id"]: p["pattern_id"] for p in patterns for m in p["members"]}
    ctx.log("cluster", note=f"{len(clusters)} groups, {len(patterns)} span >= {min_p} projects")


def step_replication(ctx: PatternContext) -> None:
    corpus, patterns, inp = ctx.data["corpus"], ctx.data["patterns"], ctx.data["in_pattern"]
    role = {m["approach_id"]: m["role"] for p in patterns for m in p["members"]}
    # by sector of the adopting approach
    sec = defaultdict(lambda: {"approaches": 0, "in_pattern": 0, "reuses": 0, "origins": 0, "patterns": Counter()})
    reg = defaultdict(lambda: {"approaches": 0, "in_pattern": 0, "reuses": 0})
    fy = defaultdict(lambda: {"approaches": 0, "first_use": 0, "reuse": 0})
    for a in corpus:
        s = sec[a["major_sector"]]
        s["approaches"] += 1
        r = reg[a["region_short"] or "Unspecified"]
        r["approaches"] += 1
        f = fy[a["fy"]] if a["fy"] else None
        if f is not None:
            f["approaches"] += 1
        pid = inp.get(a["approach_id"])
        if pid:
            s["in_pattern"] += 1
            s["patterns"][pid] += 1
            r["in_pattern"] += 1
            if role[a["approach_id"]] == "replication":
                s["reuses"] += 1
                r["reuses"] += 1
                if f is not None:
                    f["reuse"] += 1
            else:
                s["origins"] += 1
                if f is not None:
                    f["first_use"] += 1
        elif f is not None:
            f["first_use"] += 1
    labels = {p["pattern_id"]: p["label"] for p in patterns}
    by_sector = [{"sector": k, "approaches": v["approaches"], "in_pattern": v["in_pattern"], "share_in_pattern": round(v["in_pattern"] / v["approaches"], 3) if v["approaches"] else 0,
                  "reuses": v["reuses"], "origins": v["origins"], "top_patterns": [{"pattern_id": pid, "label": labels[pid], "n": n} for pid, n in v["patterns"].most_common(5)]}
                 for k, v in sec.items()]
    by_sector.sort(key=lambda x: -x["in_pattern"])
    by_region = [{"region": k, **v, "share_in_pattern": round(v["in_pattern"] / v["approaches"], 3) if v["approaches"] else 0} for k, v in reg.items()]
    by_region.sort(key=lambda x: -x["in_pattern"])
    by_fy = [{"fy": k, **v} for k, v in sorted(fy.items())]
    # region-to-region flows (origin region -> adopting region)
    flows = Counter()
    for p in patterns:
        o = p["members"][0]["region_short"]
        for m in p["members"][1:]:
            flows[(o, m["region_short"])] += 1
    n_in = len(inp)
    kpis = {"approaches": len(corpus), "projects": len({a["project_id"] for a in corpus}), "patterns": len(patterns),
            "approaches_in_patterns": n_in, "share_in_patterns": round(n_in / len(corpus), 3) if corpus else 0,
            "reuse_events": sum(p["reuse"] for p in patterns), "projects_in_patterns": len({m["project_id"] for p in patterns for m in p["members"]}),
            "max_projects_per_pattern": max((p["n_projects"] for p in patterns), default=0)}
    ctx.data.update(by_sector=by_sector, by_region=by_region, by_fy=by_fy, kpis=kpis,
                    flows=[{"from": a, "to": b, "n": n} for (a, b), n in flows.most_common()])
    ctx.log("replication", note=f"{kpis['reuse_events']} reuse events; {kpis['share_in_patterns']:.0%} of approaches belong to a replicated pattern")


def step_scaling(ctx: PatternContext) -> None:
    c = ctx.cfg("scaling", {})
    events = []
    for p in ctx.data["patterns"]:
        seen: dict[str, dict] = {}
        for m in p["members"]:
            prev = seen.get(m["country"])
            if prev and m["country"]:
                growth = (m["commitment_usd"] / prev["commitment_usd"]) if (m["commitment_usd"] and prev["commitment_usd"]) else None
                events.append({"pattern_id": p["pattern_id"], "label": p["label"], "country": m["country"], "sector": m["major_sector"],
                               "from_project": prev["project_id"], "from_fy": prev["fy"], "to_project": m["project_id"], "to_fy": m["fy"],
                               "commitment_growth": round(growth, 2) if growth else None, "type": "same-country follow-on"})
            seen.setdefault(m["country"], m)
    spread = sum(p["reuse"] for p in ctx.data["patterns"]) - len(events)
    by_sector = Counter(e["sector"] for e in events)
    ctx.data["scaling"] = {"status": c.get("status", "provisional"), "definition": " ".join((c.get("definition") or "").split()),
                           "events": events, "n_events": len(events), "n_spread": spread,
                           "with_growth": sum(1 for e in events if e["commitment_growth"] and e["commitment_growth"] > 1),
                           "by_sector": [{"sector": k, "n": n} for k, n in by_sector.most_common()]}
    ctx.log("scaling", note=f"provisional: {len(events)} same-country follow-ons, {spread} new-country adoptions")


def step_write(ctx: PatternContext) -> None:
    d, out = ctx.data, ctx.out_dir
    result = {"workflow": ctx.workflow.version, "workflow_tag": ctx.workflow.tag, "workflow_hash": ctx.workflow.hash, "config": ctx.workflow.config,
              "kpis": d["kpis"], "patterns": d["patterns"], "by_sector": d["by_sector"], "by_region": d["by_region"],
              "by_fy": d["by_fy"], "flows": d["flows"], "scaling": d["scaling"]}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _write_csv(out / "pairs.csv", d["pairs"])
    _write_csv(out / "patterns.csv", [{k: v for k, v in p.items() if k != "members"} for p in d["patterns"]])
    _write_csv(out / "pattern_members.csv", [{"pattern_id": p["pattern_id"], "pattern_label": p["label"], **m} for p in d["patterns"] for m in p["members"]])
    _write_csv(out / "by_sector.csv", d["by_sector"])
    _write_csv(out / "by_region.csv", d["by_region"])
    _write_csv(out / "by_fy.csv", d["by_fy"])
    _write_csv(out / "scaling_events.csv", d["scaling"]["events"])
    d["result"] = result
    ctx.log("write", note=str(out))
