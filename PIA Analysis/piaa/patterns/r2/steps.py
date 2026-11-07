"""Pattern workflow r2.

1. corpus     validated approaches (theme, evidence location, sector, category, country, FY)
2. match      semantic similarity of theme + original text; sector / category only add a small bonus
3. verify     the model reads ~2 pages before and after both evidence sentences and decides "same approach?"
4. group      verified pairs -> groups of the same approach (connected components)
5. classify   same approach in different countries = replication, in the same country = scaling
6. summarize  story tables by pattern, sector, region, country and fiscal year
7. write      result.json + CSVs
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ...analysis.crosswalks import major_sector, region_group
from .. import PatternContext
from ..r1.steps import _cos, _tfidf, _write_csv


# v4 names carry the category as a prefix ("Technological · CAPI"); the category is compared separately
_CAT_PREFIX = re.compile(r"^(Operational|Technological|Financial|Collaborative)\s*[·:-]\s*", re.I)


def run(ctx: PatternContext) -> None:
    for name in ctx.cfg("steps", []):
        globals()[f"step_{name}"](ctx)


# ----------------------------------------------------------------------------- 1. corpus
def step_corpus(ctx: PatternContext) -> None:
    sc = ctx.cfg("scope", {})
    ex_status, ex_adopt = set(sc.get("exclude_status", [])), set(sc.get("exclude_adoption", []))
    con = sqlite3.connect(f"file:{ctx.db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cols = {r["name"] for r in con.execute("PRAGMA table_info(approaches)")}
    adopt = "a.adoption" if "adoption" in cols else "NULL"
    rows = con.execute(f"""SELECT a.approach_id, a.project_id, a.name, a.description, a.evidence_json, a.sector, a.theme,
                                  a.category, a.category_solution, a.status, {adopt} AS adoption,
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
            "name": _CAT_PREFIX.sub("", r["name"] or ""), "description": r["description"] or "", "evidence": ev.get("text", "") or "",
            "evidence_doc": f"{ev.get('doc_type', '')} {ev.get('doc_date', '')}".strip(),
            "guid": ev.get("guid", ""), "char_start": ev.get("char_start", -1), "char_end": ev.get("char_end", -1),
            "theme": r["theme"] or "", "sector": sector, "major_sector": major_sector(sector),
            "category": r["category"] or "", "solution": r["category_solution"] or "",
            "country": (r["country"] or "").strip(), "region": r["region"] or "", "region_short": region_group(r["region"] or ""),
            "approval_date": r["approval_date"] or "", "fy": int(r["approval_fy"]) if r["approval_fy"] else None,
            "commitment_usd": r["commitment_usd"],
        })
    corpus.sort(key=lambda a: (a["approval_date"] or "9999", a["project_id"], a["approach_id"]))
    ctx.data["corpus"] = corpus
    ctx.log("corpus", note=f"{len(corpus)} approaches in {len({a['project_id'] for a in corpus})} projects")


# ----------------------------------------------------------------------------- 2. match
def _texts(corpus: list[dict], fields: list[str]) -> list[str]:
    lab = {"theme": "Theme", "evidence": "Text", "name": "Approach", "description": "Description"}
    return [". ".join(f"{lab.get(f, f)}: {a[f]}" for f in fields if a.get(f)) for a in corpus]


def _similarity(ctx: PatternContext, corpus: list[dict]):
    """Return (backend, sim(i, j))."""
    c = ctx.cfg("match", {})
    if c.get("backend", "auto") in ("auto", "embedding"):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(c.get("embedding_model", "all-MiniLM-L6-v2"))
            vecs = model.encode(_texts(corpus, c.get("text", ["theme", "evidence"])), normalize_embeddings=True, batch_size=64)
            return "embedding:" + c.get("embedding_model", "all-MiniLM-L6-v2"), lambda i, j: float(vecs[i] @ vecs[j])
        except Exception as e:  # noqa: BLE001 - optional dependency
            if c.get("backend") == "embedding":
                raise
            ctx.log("match", status="info", note=f"embedding backend unavailable ({type(e).__name__}); using TF-IDF")
    vecs = _tfidf(_texts(corpus, c.get("tfidf_text", ["theme", "name", "description", "evidence"])), 2)
    return "tfidf", lambda i, j: _cos(vecs[i], vecs[j])


def step_match(ctx: PatternContext) -> None:
    c = ctx.cfg("match", {})
    corpus = ctx.data["corpus"]
    backend, sim = _similarity(ctx, corpus)
    thr = c.get("threshold", {}).get("embedding" if backend.startswith("embedding") else "tfidf", 0.25)
    bonus = c.get("reference_bonus", {})
    k = c.get("top_k", 5)
    best: dict[int, list[tuple[float, int]]] = defaultdict(list)
    raw = {}
    for i in range(len(corpus)):
        for j in range(i + 1, len(corpus)):
            a, b = corpus[i], corpus[j]
            if a["project_id"] == b["project_id"]:
                continue
            s = sim(i, j)
            ref = []
            if a["major_sector"] == b["major_sector"]:
                s += bonus.get("same_sector", 0); ref.append("sector")
            if a["category"] and a["category"] == b["category"]:
                s += bonus.get("same_category", 0); ref.append("category")
            if a["solution"] and a["solution"] == b["solution"]:
                s += bonus.get("same_solution", 0); ref.append("solution")
            if s >= thr:
                raw[(i, j)] = (round(s, 3), ref)
                best[i].append((s, j)); best[j].append((s, i))
    keep = set()
    for i, lst in best.items():
        for s, j in sorted(lst, reverse=True)[:k]:
            keep.add((min(i, j), max(i, j)))
    pairs = []
    for (i, j) in sorted(keep, key=lambda x: -raw[x][0]):
        a, b = corpus[i], corpus[j]
        pairs.append({"i": i, "j": j, "a": a["approach_id"], "b": b["approach_id"], "project_a": a["project_id"], "project_b": b["project_id"],
                      "country_a": a["country"], "country_b": b["country"], "name_a": a["name"], "name_b": b["name"],
                      "sector_a": a["major_sector"], "sector_b": b["major_sector"], "region_a": a["region_short"], "region_b": b["region_short"],
                      "fy_a": a["fy"], "fy_b": b["fy"],
                      "score": raw[(i, j)][0], "reference_match": raw[(i, j)][1], "relation": "scaling" if _same_country(a, b) else "replication",
                      "status": "candidate", "confidence": None, "shared_solution": "", "reason": ""})
    ctx.data.update(pairs=pairs, backend=backend, match_threshold=thr)
    ctx.log("match", note=f"{backend}: {len(raw)} pairs >= {thr}, {len(pairs)} kept (top {k} per approach)")


def _same_country(a: dict, b: dict) -> bool:
    return bool(a["country"]) and a["country"].lower() == b["country"].lower()


# ----------------------------------------------------------------------------- 3. verify
def _context(ctx: PatternContext, a: dict, pages_each_side: int) -> tuple[str, bool]:
    """About ``pages_each_side`` pages before and after the evidence, evidence marked >>> <<<."""
    if ctx.index is not None and a["guid"] and a["char_start"] is not None and a["char_start"] >= 0:
        doc = ctx.index.by_guid(a["guid"])
        if doc is not None:
            from ...context import build_context
            from ...workflows.v3.steps import _render_context
            try:
                data = build_context(doc, a["char_start"], a["char_end"], pages=2 * pages_each_side)
                return _render_context(data, a["char_start"], a["char_end"]), True
            except Exception:  # noqa: BLE001 - unreadable file -> fall back to the sentence
                pass
    return f">>> {a['evidence']} <<<\n(document context not available)", False


def _cache_key(prompt_hash: str, a: dict, b: dict) -> str:
    x, y = sorted([a, b], key=lambda z: z["approach_id"])
    raw = "|".join([prompt_hash, x["approach_id"], x["evidence"], y["approach_id"], y["evidence"]])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def step_verify(ctx: PatternContext) -> None:
    c = ctx.cfg("verify", {})
    pairs, corpus = ctx.data["pairs"], ctx.data["corpus"]
    wf = ctx.workflow
    cache_path = ctx.out_dir.parent / "_verify_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if c.get("cache", True) and cache_path.exists() else {}
    phash = hashlib.sha1((wf.prompts.get("00_system", "") + wf.prompts.get("01_verify", "") + str(c.get("context_pages_each_side", 2))).encode()).hexdigest()[:10]
    todo = pairs[: c.get("max_pairs", 300)]
    hits = 0
    for p in todo:  # cached verdicts first (free)
        v = cache.get(_cache_key(phash, corpus[p["i"]], corpus[p["j"]]))
        if v:
            _apply(p, v, c.get("min_confidence", 0.6), cached=True)
            hits += 1
    pending = [p for p in todo if p["status"] == "candidate"]
    if not c.get("enabled", True) or ctx.llm is None:
        ctx.data["verify_mode"] = "not run"
        ctx.log("verify", status="skipped" if not hits else "partial",
                note=f"{'disabled' if not c.get('enabled', True) else 'no API key'}; {hits} verdicts from cache, {len(pending)} pairs left unverified")
        return
    pages = c.get("context_pages_each_side", 2)

    def check(p):
        a, b = corpus[p["i"]], corpus[p["j"]]
        ca, oka = _context(ctx, a, pages)
        cb, okb = _context(ctx, b, pages)
        prompt = wf.prompt("01_verify", project_a=a["project_id"], country_a=a["country"], fy_a=a["fy"], project_name_a=a["project_name"],
                           name_a=a["name"], theme_a=a["theme"], sector_a=a["sector"], category_a=a["category"], doc_a=a["evidence_doc"], context_a=ca,
                           project_b=b["project_id"], country_b=b["country"], fy_b=b["fy"], project_name_b=b["project_name"],
                           name_b=b["name"], theme_b=b["theme"], sector_b=b["sector"], category_b=b["category"], doc_b=b["evidence_doc"], context_b=cb)
        try:
            v = ctx.llm.complete_json("verify", wf.prompts.get("00_system", ""), prompt, retries=1)
            v = v if isinstance(v, dict) else {}
            v["context"] = "full" if (oka and okb) else "partial"
            return p, v, None
        except Exception as e:  # noqa: BLE001
            return p, None, f"{type(e).__name__}: {e}"

    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, c.get("parallel", 6))) as ex:
        for p, v, err in ex.map(check, pending):
            if err:
                p["status"], p["reason"] = "error", err
                errors += 1
                continue
            cache[_cache_key(phash, corpus[p["i"]], corpus[p["j"]])] = v
            _apply(p, v, c.get("min_confidence", 0.6))
    if c.get("cache", True):
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    ctx.data["verify_mode"] = "model"
    n_same = sum(1 for p in todo if p["status"] == "verified")
    ctx.log("verify", note=f"{len(pending)} model calls, {hits} cached; {n_same} same approach, {errors} errors")


def _apply(p: dict, v: dict, min_conf: float, cached: bool = False) -> None:
    conf = float(v.get("confidence") or 0)
    p["confidence"] = round(conf, 2)
    p["status"] = "verified" if (v.get("same") and conf >= min_conf) else "rejected"
    p["shared_solution"] = v.get("shared_solution", "") or ""
    p["reason"] = v.get("reason", "") or ""
    p["context"] = v.get("context", "")
    p["cached"] = cached


# ----------------------------------------------------------------------------- 4. group
def step_group(ctx: PatternContext) -> None:
    corpus, pairs = ctx.data["corpus"], ctx.data["pairs"]
    verified = [p for p in pairs if p["status"] == "verified"]
    use = verified if verified or ctx.data.get("verify_mode") == "model" else [p for p in pairs if p["status"] == "candidate"]
    ctx.data["basis"] = "verified" if (verified or ctx.data.get("verify_mode") == "model") else "candidates"
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for p in use:
        parent[find(p["i"])] = find(p["j"])
    comps = defaultdict(list)
    for x in list(parent):
        comps[find(x)].append(x)
    patterns = []
    for members in comps.values():
        members = sorted(set(members))   # corpus order = approval order
        if len({corpus[m]["project_id"] for m in members}) < 2:
            continue
        mset = set(members)
        links = [p for p in use if p["i"] in mset]
        label = Counter(p["shared_solution"] for p in links if p["shared_solution"]).most_common(1)
        deg = Counter([p["i"] for p in links] + [p["j"] for p in links])
        hub = max(members, key=lambda m: deg[m])
        patterns.append({"members_idx": members, "links": links,
                         "label": label[0][0] if label else corpus[hub]["name"], "label_source": "model" if label else "approach name"})
    patterns.sort(key=lambda p: (-len({corpus[m]["project_id"] for m in p["members_idx"]}), corpus[p["members_idx"][0]]["approval_date"]))
    for k, p in enumerate(patterns, 1):
        p["pattern_id"] = f"P{k:03d}"
    ctx.data["patterns_raw"] = patterns
    ctx.log("group", note=f"{len(patterns)} groups of the same approach from {len(use)} {ctx.data['basis']} pairs")


# ----------------------------------------------------------------------------- 5. classify
def step_classify(ctx: PatternContext) -> None:
    """Walk each group in approval order: the first project is the origin; a later project is SCALING when an
    earlier member is in the same country, otherwise REPLICATION (first use in a new country)."""
    corpus = ctx.data["corpus"]
    patterns, events = [], []
    for p in ctx.data["patterns_raw"]:
        seen_projects, seen_countries = set(), set()
        members = []
        for m in p["members_idx"]:
            a = corpus[m]
            if a["project_id"] in seen_projects:      # second approach of a project already in the group
                continue
            if not seen_projects:
                role = "origin"
            elif a["country"] and a["country"].lower() in seen_countries:
                role = "scaling"
            else:
                role = "replication"
            seen_projects.add(a["project_id"]); seen_countries.add(a["country"].lower())
            mem = {k: a[k] for k in ("approach_id", "project_id", "project_name", "name", "evidence", "evidence_doc", "theme", "sector",
                                     "major_sector", "category", "solution", "country", "region_short", "fy", "approval_date", "commitment_usd")}
            mem["role"] = role
            members.append(mem)
            if role != "origin":
                events.append({"pattern_id": p["pattern_id"], "label": p["label"], "type": role, "project_id": a["project_id"],
                               "country": a["country"], "region": a["region_short"], "sector": a["major_sector"], "fy": a["fy"],
                               "origin_project": members[0]["project_id"], "origin_country": members[0]["country"]})
        links = [{k: l[k] for k in ("a", "b", "project_a", "project_b", "country_a", "country_b", "score", "relation", "status", "confidence", "shared_solution", "reason", "reference_match")}
                 for l in p["links"]]
        n_rep = sum(1 for m in members if m["role"] == "replication")
        n_sc = sum(1 for m in members if m["role"] == "scaling")
        patterns.append({"pattern_id": p["pattern_id"], "label": p["label"], "label_source": p["label_source"], "members": members, "links": links,
                         "n_projects": len(members), "n_countries": len({m["country"] for m in members}), "replication": n_rep, "scaling": n_sc,
                         "countries": list(dict.fromkeys(m["country"] for m in members)), "sectors": [s for s, _ in Counter(m["major_sector"] for m in members).most_common()],
                         "themes": [s for s, _ in Counter(m["theme"] for m in members if m["theme"]).most_common(3)],
                         "first_fy": members[0]["fy"], "last_fy": members[-1]["fy"], "origin_country": members[0]["country"],
                         "mean_confidence": round(sum(l["confidence"] or 0 for l in links) / len(links), 2) if links and any(l["confidence"] for l in links) else None,
                         "type": "both" if n_rep and n_sc else ("replication" if n_rep else "scaling")})
    ctx.data.update(patterns=patterns, events=events)
    ctx.log("classify", note=f"{sum(e['type'] == 'replication' for e in events)} replication, {sum(e['type'] == 'scaling' for e in events)} scaling events")


# ----------------------------------------------------------------------------- 6. summarize
def step_summarize(ctx: PatternContext) -> None:
    corpus, patterns, events, pairs = ctx.data["corpus"], ctx.data["patterns"], ctx.data["events"], ctx.data["pairs"]
    in_pat = {m["approach_id"] for p in patterns for m in p["members"]}
    sec = defaultdict(lambda: {"approaches": 0, "in_pattern": 0, "replication": 0, "scaling": 0, "patterns": Counter()})
    reg = defaultdict(lambda: {"approaches": 0, "in_pattern": 0, "replication": 0, "scaling": 0})
    fy = defaultdict(lambda: {"approaches": 0, "first_use": 0, "replication": 0, "scaling": 0})
    for a in corpus:
        sec[a["major_sector"]]["approaches"] += 1
        reg[a["region_short"] or "Unspecified"]["approaches"] += 1
        if a["fy"]:
            fy[a["fy"]]["approaches"] += 1
        if a["approach_id"] in in_pat:
            sec[a["major_sector"]]["in_pattern"] += 1
            reg[a["region_short"] or "Unspecified"]["in_pattern"] += 1
    role_of = {m["approach_id"]: (m["role"], p["pattern_id"]) for p in patterns for m in p["members"]}
    for a in corpus:
        role, pid = role_of.get(a["approach_id"], ("first_use", None))
        if pid:
            sec[a["major_sector"]]["patterns"][pid] += 1
        if role in ("replication", "scaling"):
            sec[a["major_sector"]][role] += 1
            reg[a["region_short"] or "Unspecified"][role] += 1
        if a["fy"]:
            fy[a["fy"]]["first_use" if role in ("origin", "first_use") else role] += 1
    labels = {p["pattern_id"]: p["label"] for p in patterns}
    by_sector = sorted([{"sector": k, "approaches": v["approaches"], "in_pattern": v["in_pattern"], "replication": v["replication"], "scaling": v["scaling"],
                         "share_in_pattern": round(v["in_pattern"] / v["approaches"], 3) if v["approaches"] else 0,
                         "top_patterns": [{"pattern_id": k2, "label": labels[k2], "n": n} for k2, n in v["patterns"].most_common(5)]}
                        for k, v in sec.items()], key=lambda x: -(x["replication"] + x["scaling"]))
    by_region = sorted([{"region": k, **v, "share_in_pattern": round(v["in_pattern"] / v["approaches"], 3) if v["approaches"] else 0} for k, v in reg.items()],
                       key=lambda x: -(x["replication"] + x["scaling"]))
    by_fy = [{"fy": k, **v} for k, v in sorted(fy.items())]
    # countries: sources of replication (origin countries) and where scaling happens
    cty = defaultdict(lambda: {"originated": 0, "received": 0, "scaled": 0})
    for e in events:
        if e["type"] == "replication":
            cty[e["origin_country"]]["originated"] += 1
            cty[e["country"]]["received"] += 1
        else:
            cty[e["country"]]["scaled"] += 1
    by_country = sorted([{"country": k, **v} for k, v in cty.items() if k], key=lambda x: -(x["originated"] + x["received"] + x["scaled"]))
    st = Counter(p["status"] for p in pairs)
    kpis = {"approaches": len(corpus), "projects": len({a["project_id"] for a in corpus}),
            "candidate_pairs": len(pairs), "verified_pairs": st.get("verified", 0), "rejected_pairs": st.get("rejected", 0),
            "unverified_pairs": st.get("candidate", 0) + st.get("error", 0),
            "patterns": len(patterns), "approaches_in_patterns": len(in_pat), "share_in_patterns": round(len(in_pat) / len(corpus), 3) if corpus else 0,
            "replication_events": sum(e["type"] == "replication" for e in events), "scaling_events": sum(e["type"] == "scaling" for e in events),
            "replication_patterns": sum(p["replication"] > 0 for p in patterns), "scaling_patterns": sum(p["scaling"] > 0 for p in patterns),
            "max_projects_per_pattern": max((p["n_projects"] for p in patterns), default=0)}
    ctx.data.update(by_sector=by_sector, by_region=by_region, by_fy=by_fy, by_country=by_country, kpis=kpis)
    ctx.log("summarize", note=f"{kpis['patterns']} same-approach groups; {kpis['replication_events']} replication, {kpis['scaling_events']} scaling")


# ----------------------------------------------------------------------------- 7. write
def step_write(ctx: PatternContext) -> None:
    d, out = ctx.data, ctx.out_dir
    pairs = [{k: v for k, v in p.items() if k not in ("i", "j")} for p in d["pairs"]]
    result = {"workflow": ctx.workflow.version, "workflow_tag": ctx.workflow.tag, "workflow_hash": ctx.workflow.hash, "config": ctx.workflow.config,
              "method": {"backend": d["backend"], "threshold": d["match_threshold"], "verify": d.get("verify_mode", "not run"), "basis": d["basis"]},
              "kpis": d["kpis"], "patterns": d["patterns"], "pairs": pairs, "events": d["events"], "by_sector": d["by_sector"],
              "by_region": d["by_region"], "by_fy": d["by_fy"], "by_country": d["by_country"]}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _write_csv(out / "pairs.csv", pairs)
    _write_csv(out / "patterns.csv", [{k: v for k, v in p.items() if k not in ("members", "links")} for p in d["patterns"]])
    _write_csv(out / "pattern_members.csv", [{"pattern_id": p["pattern_id"], "pattern_label": p["label"], **m} for p in d["patterns"] for m in p["members"]])
    _write_csv(out / "events.csv", d["events"])
    for name in ("by_sector", "by_region", "by_fy", "by_country"):
        _write_csv(out / f"{name}.csv", d[name])
    d["result"] = result
    ctx.log("write", note=str(out))
