"""Pattern workflow r3 - two columns per approach, database only.

1. corpus     validated approaches with evidence passages, explicit references, country, sector, FY
2. cues       rule scan of the passages: replication / scaling language, P-codes, project names
3. match      semantic similarity to approaches of EARLIER projects (top-k candidates)
4. judge      one model call per approach: replication level + source project; which candidates are the same approach
5. classify   replication = confirmed / likely (+ source); scaling = same approach earlier in same country + sector
6. summarize  story tables (by sector, region, country, FY; confirmed vs likely)
7. write      result.json + CSVs, the two columns written back to the database

The result keeps the r2 shape (patterns / events / pairs / by_*) so the Patterns page works, and adds
``approaches`` - one row per approach with ``replication`` and ``scaling`` columns.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ...analysis.crosswalks import major_sector, region_group
from .. import PatternContext
from ..r1.steps import _cos, _tfidf, _write_csv

PCODE_RE = re.compile(r"\bP\d{6}\b")
_CAT_PREFIX = re.compile(r"^(Operational|Technological|Financial|Collaborative)\s*[·:-]\s*", re.I)
LEVEL_RANK = {"confirmed": 2, "likely": 1, "none": 0, "": 0}


def run(ctx: PatternContext) -> None:
    for name in ctx.cfg("steps", []):
        globals()[f"step_{name}"](ctx)


# ----------------------------------------------------------------------------- 1. corpus
def step_corpus(ctx: PatternContext) -> None:
    sc = ctx.cfg("scope", {})
    ex_status, ex_adopt = set(sc.get("exclude_status", [])), set(sc.get("exclude_adoption", []))
    max_p = sc.get("max_passages", 4)
    con = sqlite3.connect(f"file:{ctx.db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cols = {r["name"] for r in con.execute("PRAGMA table_info(approaches)")}
    adopt = "a.adoption" if "adoption" in cols else "NULL"
    extra = "a.extra_json" if "extra_json" in cols else "NULL"
    rows = con.execute(f"""SELECT a.approach_id, a.project_id, a.name, a.description, a.evidence_json, {extra} AS extra_json,
                                  a.replication_json, a.sector, a.category, a.status, {adopt} AS adoption,
                                  p.project_name, p.country, p.region, p.approval_date, p.approval_fy, p.commitment_usd, p.sectors_json
                           FROM approaches a JOIN projects p USING(project_id)""").fetchall()
    projects = {r["project_id"]: dict(r) for r in con.execute("SELECT project_id, project_name, country, region, approval_date, approval_fy FROM projects")}
    out_of_scope = {r[0] for r in con.execute("SELECT project_id FROM review WHERE status='out of scope'")}   # v6.9 scope step
    con.close()
    corpus = []
    for r in rows:
        if r["status"] in ex_status or (r["adoption"] or "") in ex_adopt or r["project_id"] in out_of_scope:
            continue
        ev = json.loads(r["evidence_json"] or "{}")
        extras = [e for e in json.loads(r["extra_json"] or "[]") if isinstance(e, dict) and e.get("text")]
        passages = [{"text": ev.get("text", "") or "", "doc": f"{ev.get('doc_type', '')} {ev.get('doc_date', '')}".strip(), "kind": "evidence"}]
        passages += [{"text": e["text"], "doc": f"{e.get('doc_type', '')} {e.get('doc_date', '')}".strip(), "kind": "extra"} for e in extras[: max_p - 1]]
        links = [l for l in json.loads(r["replication_json"] or "[]") if isinstance(l, dict)]
        psec = sorted(json.loads(r["sectors_json"] or "[]"), key=lambda x: -(x.get("pct") or 0))
        sector = r["sector"] or (psec[0]["name"] if psec else "")
        corpus.append({
            "approach_id": r["approach_id"], "project_id": r["project_id"], "project_name": r["project_name"] or "",
            "name": _CAT_PREFIX.sub("", r["name"] or ""), "description": r["description"] or "",
            "evidence": passages[0]["text"], "evidence_doc": passages[0]["doc"], "passages": passages,
            "explicit_refs": [{"project_id": l.get("other_project_id", ""), "evidence": (l.get("evidence") or "")[:300], "score": l.get("score"),
                               "direction": l.get("direction", "")}
                              for l in links if l.get("kind") == "explicit_reference" and l.get("other_project_id")],
            "stored_similar": [{"approach_id": l.get("other_approach_id") or "", "project_id": l.get("other_project_id", ""), "score": l.get("score"),
                                "direction": l.get("direction", "")}
                               for l in links if l.get("kind") == "similar_approach" and l.get("other_project_id")],
            "theme": "", "sector": sector, "major_sector": major_sector(sector), "category": r["category"] or "", "solution": "",
            "country": (r["country"] or "").strip(), "region": r["region"] or "", "region_short": region_group(r["region"] or ""),
            "approval_date": r["approval_date"] or "", "fy": int(r["approval_fy"]) if r["approval_fy"] else None,
            "commitment_usd": r["commitment_usd"],
        })
    corpus.sort(key=lambda a: (a["approval_date"] or "9999", a["project_id"], a["approach_id"]))
    ctx.data.update(corpus=corpus, projects=projects)
    ctx.log("corpus", note=f"{len(corpus)} approaches in {len({a['project_id'] for a in corpus})} projects; "
                           f"{sum(1 for a in corpus if a['explicit_refs'])} carry explicit project references")


# ----------------------------------------------------------------------------- 2. cues
def _rx(items: list[str]) -> re.Pattern:
    return re.compile("(" + "|".join(items) + ")", re.IGNORECASE)


def step_cues(ctx: PatternContext) -> None:
    c = ctx.cfg("cues", {})
    rep_rx, sca_rx = _rx(c.get("replication", ["replicat\\w*"])), _rx(c.get("scaling", ["scal(?:e|es|ed|ing)[- ]?up"]))
    projects = ctx.data["projects"]
    min_words = c.get("min_project_name_words", 3)
    names = [(pid, p["project_name"]) for pid, p in projects.items() if p.get("project_name") and len(p["project_name"].split()) >= min_words]
    n_rep = n_named = 0
    for a in ctx.data["corpus"]:
        text = " ".join(p["text"] for p in a["passages"])
        a["rep_cues"] = sorted({m.group(0).lower() for m in rep_rx.finditer(text)})
        a["sca_cues"] = sorted({m.group(0).lower() for m in sca_rx.finditer(text)})
        refs = {}
        for code in PCODE_RE.findall(text):
            if code != a["project_id"]:
                refs[code] = "pcode"
        low = text.lower()
        for pid, nm in names:
            if pid != a["project_id"] and nm.lower() in low:
                refs.setdefault(pid, "name")
        a["named_refs"] = [{"project_id": k, "how": v} for k, v in refs.items()]
        n_rep += bool(a["rep_cues"]); n_named += bool(refs)
    ctx.log("cues", note=f"{n_rep} approaches with replication language, {n_named} naming another project in their passages")


# ----------------------------------------------------------------------------- 3. match
def _texts(corpus, fields):
    lab = {"evidence": "Text", "name": "Approach", "description": "Description"}
    return [". ".join(f"{lab.get(f, f)}: {a[f]}" for f in fields if a.get(f)) for a in corpus]


def _similarity(ctx, corpus):
    c = ctx.cfg("match", {})
    fields = c.get("text", ["name", "description", "evidence"])
    if c.get("backend", "auto") in ("auto", "embedding"):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(c.get("embedding_model", "all-MiniLM-L6-v2"))
            vecs = model.encode(_texts(corpus, fields), normalize_embeddings=True, batch_size=64)
            return "embedding:" + c.get("embedding_model", "all-MiniLM-L6-v2"), lambda i, j: float(vecs[i] @ vecs[j])
        except Exception as e:  # noqa: BLE001 - optional dependency
            if c.get("backend") == "embedding":
                raise
            ctx.log("match", status="info", note=f"embedding backend unavailable ({type(e).__name__}); using TF-IDF")
    vecs = _tfidf(_texts(corpus, fields), 2)
    return "tfidf", lambda i, j: _cos(vecs[i], vecs[j])


def step_match(ctx: PatternContext) -> None:
    """Candidates = approaches of EARLIER projects (approval date before) above the threshold, top-k per approach."""
    c = ctx.cfg("match", {})
    corpus = ctx.data["corpus"]
    backend, sim = _similarity(ctx, corpus)
    thr = c.get("threshold", {}).get("embedding" if backend.startswith("embedding") else "tfidf", 0.2)
    bonus, k = c.get("reference_bonus", {}), c.get("top_k", 5)
    cands: dict[str, list[dict]] = {}
    by_id = {a["approach_id"]: a for a in corpus}
    idx = {a["approach_id"]: i for i, a in enumerate(corpus)}
    n_pairs = 0
    for j, b in enumerate(corpus):          # b = the later approach under review
        found = []
        for i, a in enumerate(corpus):      # a = earlier candidate
            if a["project_id"] == b["project_id"] or not a["approval_date"] or not b["approval_date"] or a["approval_date"] >= b["approval_date"]:
                continue
            s = sim(i, j)
            ref = []
            if a["major_sector"] == b["major_sector"]:
                s += bonus.get("same_sector", 0); ref.append("sector")
            if a["category"] and a["category"] == b["category"]:
                s += bonus.get("same_category", 0); ref.append("category")
            if s >= thr:
                found.append({"candidate_id": a["approach_id"], "idx": i, "score": round(s, 3), "reference_match": ref,
                              "same_country": _same_country(a, b), "same_sector": a["major_sector"] == b["major_sector"]})
        have = {f["candidate_id"] for f in found}
        for l in b.get("stored_similar", []):        # similar_approach links stored by the approach workflow (TF-IDF >= 0.30 over the portfolio)
            a = by_id.get(l["approach_id"])
            if a is None or a["project_id"] == b["project_id"] or a["approach_id"] in have or (a["approval_date"] or "9999") >= (b["approval_date"] or ""):
                continue
            found.append({"candidate_id": a["approach_id"], "idx": idx[a["approach_id"]], "score": round(float(l["score"] or 0), 3), "reference_match": ["stored_link"],
                          "same_country": _same_country(a, b), "same_sector": a["major_sector"] == b["major_sector"]})
        found.sort(key=lambda x: -x["score"])
        keep = found[:k]
        extra = c.get("always_same_sector_country", 0)
        if extra:   # scaling candidates: best earlier approaches of the same country + sector, even below the threshold
            kept = {f["candidate_id"] for f in keep}
            local = []
            for i, a in enumerate(corpus):
                if a["project_id"] == b["project_id"] or a["approach_id"] in kept or not _same_country(a, b) or a["major_sector"] != b["major_sector"]:
                    continue
                if not a["approval_date"] or not b["approval_date"] or a["approval_date"] >= b["approval_date"]:
                    continue
                local.append({"candidate_id": a["approach_id"], "idx": i, "score": round(sim(i, j), 3), "reference_match": ["sector", "country"],
                              "same_country": True, "same_sector": True})
            local.sort(key=lambda x: -x["score"])
            keep += local[:extra]
        cands[b["approach_id"]] = keep
        n_pairs += len(keep)
    ctx.data.update(candidates=cands, backend=backend, match_threshold=thr)
    ctx.log("match", note=f"{backend}: {n_pairs} candidate pairs >= {thr} (top {k} earlier approaches per approach)")


def _same_country(a, b) -> bool:
    return bool(a["country"]) and a["country"].lower() == b["country"].lower()


# ----------------------------------------------------------------------------- 4. judge
def _cut(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + " ..."


def _prompt(ctx, a, cands, by_id):
    projects = ctx.data["projects"]
    wf = ctx.workflow
    passages = "\n".join(f"[{n}] ({p['doc']}) {_cut(p['text'], 900)}" for n, p in enumerate(a["passages"], 1)) or "(none)"
    named = "; ".join(f"{r['project_id']} - {_cut(projects.get(r['project_id'], {}).get('project_name', 'not in portfolio'), 80)} - "
                      f"{projects.get(r['project_id'], {}).get('country', '')} - {projects.get(r['project_id'], {}).get('approval_date', '')}"
                      for r in a["named_refs"]) or "none"
    explicit = "; ".join(f"{r['project_id']} (\"{_cut(r['evidence'], 200)}\")" for r in a["explicit_refs"][:4]) or "none"
    cl = []
    for c in cands:
        b = by_id[c["candidate_id"]]
        cl.append(f"- candidate_id: {b['approach_id']} | project {b['project_id']} ({b['country']}, FY{b['fy']}, sector: {b['sector']}) - {_cut(b['project_name'], 80)}\n"
                  f"  name: {b['name']}\n  description: {_cut(b['description'], 300)}\n  text: \"{_cut(b['evidence'], 400)}\"\n"
                  f"  similarity {c['score']}{' · same country' if c['same_country'] else ''}{' · same sector' if c['same_sector'] else ''}")
    return wf.prompt("01_judge", approach_id=a["approach_id"], project_id=a["project_id"], country=a["country"], fy=a["fy"], sector=a["sector"],
                     project_name=a["project_name"], name=a["name"], description=_cut(a["description"], 400), category=a["category"],
                     n_passages=len(a["passages"]), passages=passages, rep_cues=", ".join(a["rep_cues"]) or "none",
                     sca_cues=", ".join(a["sca_cues"]) or "none", named_refs=named, explicit_refs=explicit,
                     candidates="\n".join(cl) or "(none)")


def step_judge(ctx: PatternContext) -> None:
    c = ctx.cfg("judge", {})
    corpus, cands = ctx.data["corpus"], ctx.data["candidates"]
    by_id = {a["approach_id"]: a for a in corpus}
    wf = ctx.workflow
    todo = [a for a in corpus if cands.get(a["approach_id"]) or a["rep_cues"] or a["named_refs"] or a["explicit_refs"]]
    cache_path = ctx.out_dir.parent / "_judge_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if c.get("cache", True) and cache_path.exists() else {}
    phash = hashlib.sha1((wf.prompts.get("00_system", "") + wf.prompts.get("01_judge", "")).encode()).hexdigest()[:10]
    judg, pending, hits = {}, [], 0
    prompts = {}
    for a in todo:
        prompts[a["approach_id"]] = _prompt(ctx, a, cands.get(a["approach_id"], []), by_id)
        key = hashlib.sha1((phash + prompts[a["approach_id"]]).encode("utf-8")).hexdigest()[:16]
        if key in cache:
            judg[a["approach_id"]] = cache[key]; hits += 1
        else:
            pending.append((a, key))
    ctx.data["judgements"] = judg
    if not c.get("enabled", True) or ctx.llm is None:
        ctx.data["judge_mode"] = "not run"
        ctx.log("judge", status="skipped" if not hits else "partial",
                note=f"{'disabled' if not c.get('enabled', True) else 'no API key'}; {hits} judgements from cache, {len(pending)} approaches not judged")
        return

    def call(item):
        a, key = item
        try:
            v = ctx.llm.complete_json("judge", wf.prompts.get("00_system", ""), prompts[a["approach_id"]], retries=1, cache_system=True)
            return a["approach_id"], key, (v if isinstance(v, dict) else {}), None
        except Exception as e:  # noqa: BLE001
            return a["approach_id"], key, None, f"{type(e).__name__}: {e}"

    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, c.get("parallel", 6))) as ex:
        for aid, key, v, err in ex.map(call, pending):
            if err:
                judg[aid] = {"_error": err}; errors += 1
                continue
            cache[key] = v; judg[aid] = v
    if c.get("cache", True):
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    ctx.data["judge_mode"] = "model"
    ctx.log("judge", note=f"{len(pending)} model calls, {hits} cached, {errors} errors; {len(corpus) - len(todo)} approaches had nothing to judge")


# ----------------------------------------------------------------------------- 5. classify
def step_classify(ctx: PatternContext) -> None:
    c = ctx.cfg("classify", {})
    jc = ctx.cfg("judge", {})
    min_conf, min_conf_sc = jc.get("min_confidence", 0.6), jc.get("min_confidence_scaling", 0.5)
    corpus, cands, judg, projects = ctx.data["corpus"], ctx.data["candidates"], ctx.data["judgements"], ctx.data["projects"]
    by_id = {a["approach_id"]: a for a in corpus}
    req = set(c.get("scaling_requires", ["same_country", "same_sector"]))
    backend_key = "embedding" if ctx.data.get("backend", "").startswith("embedding") else "tfidf"
    rule_score = c.get("rule_min_score", {}).get(backend_key, 0.3)     # similarity accepted without a model verdict
    model_ran = ctx.data.get("judge_mode") == "model"
    pairs, rows, events = [], [], []
    n_rule = 0
    for a in corpus:
        j = judg.get(a["approach_id"]) or {}
        verdicts = {v.get("candidate_id"): v for v in (j.get("candidates") or []) if isinstance(v, dict)}
        same = []   # verified same / closely similar candidates (earlier projects)
        for cd in cands.get(a["approach_id"], []):
            b = by_id[cd["candidate_id"]]
            v = verdicts.get(cd["candidate_id"])
            status, conf = "candidate", None
            if v is not None:
                conf = round(float(v.get("confidence") or 0), 2)
                status = "verified" if (v.get("same") and conf >= min_conf_sc) else "rejected"
            elif j.get("_error"):
                status = "error"
            elif not model_ran and cd["score"] >= rule_score:            # rules only: strong similarity counts
                status = "verified"; conf = None
            relation = "scaling" if (cd["same_country"] and cd["same_sector"]) else "replication"
            pairs.append({"a": b["approach_id"], "b": a["approach_id"], "project_a": b["project_id"], "project_b": a["project_id"],
                          "country_a": b["country"], "country_b": a["country"], "name_a": b["name"], "name_b": a["name"],
                          "sector_a": b["major_sector"], "sector_b": a["major_sector"], "region_a": b["region_short"], "region_b": a["region_short"],
                          "fy_a": b["fy"], "fy_b": a["fy"], "score": cd["score"], "reference_match": cd["reference_match"], "relation": relation,
                          "status": status, "confidence": conf, "shared_solution": (v or {}).get("shared_solution", "") or "",
                          "reason": (v or {}).get("reason", "") or (j.get("_error", "") if status == "error" else "")})
            if status == "verified":
                same.append({**cd, "confidence": conf, "shared_solution": (v or {}).get("shared_solution", "")})
        # ---- replication column
        r = j.get("replication") or {}
        if not j and not model_ran:            # rules only (no API key / no judgement): explicit references + cue language
            r = _rule_replication(a, same, by_id)
            n_rule += bool(r)
        level = (r.get("level") or "none").lower()
        if level not in ("confirmed", "likely"):
            level = "none"
        if level == "none" and c.get("explicit_ref_upgrade", True):
            # the full documents (read at extraction time) refer to an earlier project next to replication language,
            # and that project carries a same / similar approach -> confirmed, source = that project
            strong = {e["project_id"] for e in a["explicit_refs"] if e.get("direction") == "replicates" and (e.get("score") or 0) >= 0.9}
            hit = [s_ for s_ in same if by_id[s_["candidate_id"]]["project_id"] in strong]
            if hit:
                best = max(hit, key=lambda s_: (s_["confidence"] or 0, s_["score"]))
                bb = by_id[best["candidate_id"]]
                ev = next((e for e in a["explicit_refs"] if e["project_id"] == bb["project_id"]), {})
                r = {"level": "confirmed", "source_project_id": bb["project_id"], "source_candidate_id": bb["approach_id"], "source_text": bb["project_id"],
                     "source_quote": ev.get("evidence", ""), "reason": "explicit reference to this earlier project next to replication language in the full documents, and the project carries a similar approach"}
                level = "confirmed"
        src_pid = (r.get("source_project_id") or "").strip()
        src_cand = (r.get("source_candidate_id") or "").strip()
        if src_cand and src_cand in by_id and not src_pid:
            src_pid = by_id[src_cand]["project_id"]
        if not PCODE_RE.fullmatch(src_pid or ""):
            src_pid = ""
        if src_pid == a["project_id"]:
            src_pid, level = "", "none" if level == "confirmed" else level
        note = ""
        if level == "confirmed" and not src_pid and not (r.get("source_text") or "").strip():
            level, note = "likely", "downgraded: no identifiable source"
        if level == "likely" and c.get("likely_requires_match", True):
            cross = [s for s in same if not s["same_country"] and (s["confidence"] is None or s["confidence"] >= min_conf)]
            if cross:
                best = max(cross, key=lambda s: (s["confidence"] or 0, s["score"]))
                if not src_pid:
                    src_pid = by_id[best["candidate_id"]]["project_id"]
                    src_cand = best["candidate_id"]
            elif not src_pid:
                level, note = "none", "likely not supported: no same approach in an earlier project of another country"
        rep_src = {"project_id": src_pid, "project_name": projects.get(src_pid, {}).get("project_name", ""),
                   "country": projects.get(src_pid, {}).get("country", ""), "in_portfolio": src_pid in projects,
                   "approach_id": src_cand if src_cand in by_id else ""}
        # ---- scaling column: earliest verified same approach that meets the requirements
        sc_ok = [s for s in same if ("same_country" not in req or s["same_country"]) and ("same_sector" not in req or s["same_sector"])]
        sc_src = None
        if sc_ok:
            s = min(sc_ok, key=lambda s: (by_id[s["candidate_id"]]["approval_date"], -(s["confidence"] or 0)))
            b = by_id[s["candidate_id"]]
            sc_src = {"project_id": b["project_id"], "project_name": b["project_name"], "approach_id": b["approach_id"], "country": b["country"],
                      "confidence": s["confidence"], "shared_solution": s["shared_solution"]}
        a.update(replication_level=level, replication_source=rep_src, replication_quote=(r.get("source_quote") or "")[:400],
                 replication_reason=(r.get("reason") or "") + (f" [{note}]" if note else ""), replication_text=(r.get("source_text") or "")[:200],
                 scaling="scaling" if sc_src else "", scaling_source=sc_src or {}, same_approach=[s["candidate_id"] for s in same])
        rows.append({"approach_id": a["approach_id"], "project_id": a["project_id"], "project_name": a["project_name"], "country": a["country"],
                     "region": a["region_short"], "sector": a["major_sector"], "fy": a["fy"], "approach": a["name"], "category": a["category"],
                     "replication": level if level != "none" else "",
                     "replication_source_project": src_pid, "replication_source_name": rep_src["project_name"], "replication_source_country": rep_src["country"],
                     "replication_source_in_portfolio": rep_src["in_portfolio"], "replication_source_text": a["replication_text"],
                     "replication_quote": a["replication_quote"], "replication_reason": a["replication_reason"],
                     "scaling": a["scaling"], "scaling_source_project": (sc_src or {}).get("project_id", ""),
                     "scaling_source_name": (sc_src or {}).get("project_name", ""), "scaling_confidence": (sc_src or {}).get("confidence"),
                     "same_approach_in": ";".join(by_id[x]["project_id"] for x in a["same_approach"])})
        if level != "none":
            events.append({"pattern_id": "", "label": a["name"], "type": "replication", "level": level, "project_id": a["project_id"], "approach_id": a["approach_id"],
                           "country": a["country"], "region": a["region_short"], "sector": a["major_sector"], "fy": a["fy"],
                           "origin_project": src_pid, "origin_country": rep_src["country"]})
        if sc_src:
            events.append({"pattern_id": "", "label": a["name"], "type": "scaling", "level": "", "project_id": a["project_id"], "approach_id": a["approach_id"],
                           "country": a["country"], "region": a["region_short"], "sector": a["major_sector"], "fy": a["fy"],
                           "origin_project": sc_src["project_id"], "origin_country": sc_src["country"]})
    patterns = _groups(corpus, pairs, events)
    ctx.data.update(pairs=pairs, approach_rows=rows, events=events, patterns=patterns, basis="verified" if model_ran else "rules")
    lv = Counter(a["replication_level"] for a in corpus)
    ctx.log("classify", note=f"replication: {lv.get('confirmed', 0)} confirmed, {lv.get('likely', 0)} likely; scaling: {sum(1 for a in corpus if a['scaling'])}"
                              + ("" if model_ran else f" (rules only, similarity >= {rule_score}; {n_rule} replication verdicts from explicit references / cues)"))


def _rule_replication(a: dict, same: list[dict], by_id: dict) -> dict:
    """Without a model verdict: CONFIRMED = an explicit reference to an EARLIER project found near replication language
    when the approach was extracted (score 0.9), or a project named in the passages next to replication language;
    LIKELY = replication language in the passages + a similar earlier approach in another country."""
    earlier = [e for e in a["explicit_refs"] if e.get("direction") == "replicates"]
    strong = [e for e in earlier if (e.get("score") or 0) >= 0.9]
    if strong:
        e = strong[0]
        return {"level": "confirmed", "source_project_id": e["project_id"], "source_text": e["project_id"], "source_quote": e.get("evidence", ""),
                "reason": "rule: explicit reference to an earlier project next to replication language (found when the approach was extracted)"}
    if a["named_refs"] and a["rep_cues"]:
        pid = a["named_refs"][0]["project_id"]
        return {"level": "confirmed", "source_project_id": pid, "source_text": pid, "source_quote": "", "reason": "rule: earlier project named in the passages together with replication language"}
    if a["rep_cues"]:
        cross = [s for s in same if not s["same_country"]]
        if cross:
            b = by_id[max(cross, key=lambda s: s["score"])["candidate_id"]]
            return {"level": "likely", "source_project_id": b["project_id"], "source_candidate_id": b["approach_id"], "source_text": "",
                    "source_quote": "", "reason": f"rule: replication language ({', '.join(a['rep_cues'][:3])}) + similar earlier approach in {b['country']}"}
        return {"level": "none", "reason": "rule: replication language but no similar earlier approach in another country"}
    return {}


def _groups(corpus, pairs, events) -> list[dict]:
    """Same-approach groups (for the Patterns page): verified pairs + confirmed/likely source links -> connected components."""
    by_id = {a["approach_id"]: a for a in corpus}
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    use = [p for p in pairs if p["status"] == "verified"]
    for p in use:
        parent[find(p["a"])] = find(p["b"])
    for a in corpus:
        s = a.get("replication_source", {})
        if s.get("approach_id"):
            parent[find(s["approach_id"])] = find(a["approach_id"])
    comps = defaultdict(list)
    for x in list(parent):
        comps[find(x)].append(x)
    out = []
    for members in comps.values():
        ms = sorted(members, key=lambda x: (by_id[x]["approval_date"] or "9999", x))
        if len({by_id[m]["project_id"] for m in ms}) < 2:
            continue
        seen, mem = set(), []
        for m in ms:
            a = by_id[m]
            if a["project_id"] in seen:
                continue
            seen.add(a["project_id"])
            role = "origin" if not mem else ("scaling" if a.get("scaling") else ("replication" if a["replication_level"] != "none" else "same"))
            d = {k: a[k] for k in ("approach_id", "project_id", "project_name", "name", "evidence", "evidence_doc", "theme", "sector", "major_sector",
                                   "category", "solution", "country", "region_short", "fy", "approval_date", "commitment_usd")}
            d.update(role=role, replication_level=a["replication_level"], scaling=a["scaling"])
            mem.append(d)
        mset = set(ms)
        links = [{k: p[k] for k in ("a", "b", "project_a", "project_b", "country_a", "country_b", "score", "relation", "status", "confidence", "shared_solution", "reason", "reference_match")}
                 for p in use if p["a"] in mset and p["b"] in mset]
        label = Counter(l["shared_solution"] for l in links if l["shared_solution"]).most_common(1)
        n_rep, n_sc = sum(m["role"] == "replication" for m in mem), sum(m["role"] == "scaling" for m in mem)
        out.append({"label": label[0][0] if label else mem[0]["name"], "label_source": "model" if label else "approach name", "members": mem, "links": links,
                    "n_projects": len(mem), "n_countries": len({m["country"] for m in mem}), "replication": n_rep, "scaling": n_sc,
                    "countries": list(dict.fromkeys(m["country"] for m in mem)), "sectors": [s for s, _ in Counter(m["major_sector"] for m in mem).most_common()],
                    "themes": [], "first_fy": mem[0]["fy"], "last_fy": mem[-1]["fy"], "origin_country": mem[0]["country"],
                    "mean_confidence": round(sum(l["confidence"] or 0 for l in links) / len(links), 2) if links else None,
                    "type": "both" if n_rep and n_sc else ("replication" if n_rep else ("scaling" if n_sc else "same"))})
    out.sort(key=lambda p: (-p["n_projects"], p["members"][0]["approval_date"]))
    for k, p in enumerate(out, 1):
        p["pattern_id"] = f"P{k:03d}"
        for m in p["members"]:
            for e in events:
                if e["approach_id"] == m["approach_id"]:
                    e["pattern_id"] = p["pattern_id"]
    return out


# ----------------------------------------------------------------------------- 6. summarize
def step_summarize(ctx: PatternContext) -> None:
    corpus, patterns, events, pairs = ctx.data["corpus"], ctx.data["patterns"], ctx.data["events"], ctx.data["pairs"]
    in_pat = {m["approach_id"] for p in patterns for m in p["members"]}
    sec = defaultdict(lambda: {"approaches": 0, "in_pattern": 0, "replication": 0, "confirmed": 0, "likely": 0, "scaling": 0, "patterns": Counter()})
    reg = defaultdict(lambda: {"approaches": 0, "in_pattern": 0, "replication": 0, "confirmed": 0, "likely": 0, "scaling": 0})
    fy = defaultdict(lambda: {"approaches": 0, "first_use": 0, "replication": 0, "scaling": 0})
    pid_of = {m["approach_id"]: p["pattern_id"] for p in patterns for m in p["members"]}
    for a in corpus:
        s, r = sec[a["major_sector"]], reg[a["region_short"] or "Unspecified"]
        s["approaches"] += 1; r["approaches"] += 1
        if a["approach_id"] in in_pat:
            s["in_pattern"] += 1; r["in_pattern"] += 1
            s["patterns"][pid_of[a["approach_id"]]] += 1
        lv = a["replication_level"]
        if lv != "none":
            s["replication"] += 1; r["replication"] += 1; s[lv] += 1; r[lv] += 1
        if a["scaling"]:
            s["scaling"] += 1; r["scaling"] += 1
        if a["fy"]:
            f = fy[a["fy"]]; f["approaches"] += 1
            if lv != "none":
                f["replication"] += 1
            if a["scaling"]:
                f["scaling"] += 1
            if lv == "none" and not a["scaling"]:
                f["first_use"] += 1
    labels = {p["pattern_id"]: p["label"] for p in patterns}
    by_sector = sorted([{"sector": k, **{x: v[x] for x in ("approaches", "in_pattern", "replication", "confirmed", "likely", "scaling")},
                         "share_in_pattern": round(v["in_pattern"] / v["approaches"], 3) if v["approaches"] else 0,
                         "share_replication": round(v["replication"] / v["approaches"], 3) if v["approaches"] else 0,
                         "share_scaling": round(v["scaling"] / v["approaches"], 3) if v["approaches"] else 0,
                         "top_patterns": [{"pattern_id": k2, "label": labels[k2], "n": n} for k2, n in v["patterns"].most_common(5)]}
                        for k, v in sec.items()], key=lambda x: -(x["replication"] + x["scaling"]))
    by_region = sorted([{"region": k, **v, "share_in_pattern": round(v["in_pattern"] / v["approaches"], 3) if v["approaches"] else 0} for k, v in reg.items()],
                       key=lambda x: -(x["replication"] + x["scaling"]))
    by_fy = [{"fy": k, **v} for k, v in sorted(fy.items())]
    cty = defaultdict(lambda: {"originated": 0, "received": 0, "scaled": 0})
    for e in events:
        if e["type"] == "replication":
            if e["origin_country"]:
                cty[e["origin_country"]]["originated"] += 1
            cty[e["country"]]["received"] += 1
        else:
            cty[e["country"]]["scaled"] += 1
    by_country = sorted([{"country": k, **v} for k, v in cty.items() if k], key=lambda x: -(x["originated"] + x["received"] + x["scaled"]))
    st = Counter(p["status"] for p in pairs)
    lv = Counter(a["replication_level"] for a in corpus)
    kpis = {"approaches": len(corpus), "projects": len({a["project_id"] for a in corpus}),
            "judged": len(ctx.data.get("judgements", {})), "candidate_pairs": len(pairs), "verified_pairs": st.get("verified", 0),
            "rejected_pairs": st.get("rejected", 0), "unverified_pairs": st.get("candidate", 0) + st.get("error", 0),
            "patterns": len(patterns), "approaches_in_patterns": len(in_pat), "share_in_patterns": round(len(in_pat) / len(corpus), 3) if corpus else 0,
            "replication_events": lv.get("confirmed", 0) + lv.get("likely", 0), "replication_confirmed": lv.get("confirmed", 0),
            "replication_likely": lv.get("likely", 0), "replication_source_in_portfolio": sum(1 for a in corpus if a["replication_level"] != "none" and a["replication_source"].get("in_portfolio")),
            "scaling_events": sum(1 for a in corpus if a["scaling"]),
            "replication_patterns": sum(p["replication"] > 0 for p in patterns), "scaling_patterns": sum(p["scaling"] > 0 for p in patterns),
            "max_projects_per_pattern": max((p["n_projects"] for p in patterns), default=0)}
    ctx.data.update(by_sector=by_sector, by_region=by_region, by_fy=by_fy, by_country=by_country, kpis=kpis)
    ctx.log("summarize", note=f"{kpis['replication_confirmed']} confirmed + {kpis['replication_likely']} likely replication; {kpis['scaling_events']} scaling; {kpis['patterns']} same-approach groups")


# ----------------------------------------------------------------------------- 7. write
def step_write(ctx: PatternContext) -> None:
    d, out = ctx.data, ctx.out_dir
    result = {"workflow": ctx.workflow.version, "workflow_tag": ctx.workflow.tag, "workflow_hash": ctx.workflow.hash, "config": ctx.workflow.config,
              "method": {"backend": d["backend"], "threshold": d["match_threshold"], "verify": d.get("judge_mode", "not run"), "basis": d["basis"],
                         "columns": True},
              "kpis": d["kpis"], "approaches": d["approach_rows"], "patterns": d["patterns"], "pairs": d["pairs"], "events": d["events"],
              "by_sector": d["by_sector"], "by_region": d["by_region"], "by_fy": d["by_fy"], "by_country": d["by_country"]}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _write_csv(out / "approaches.csv", d["approach_rows"])
    _write_csv(out / "pairs.csv", d["pairs"])
    _write_csv(out / "patterns.csv", [{k: v for k, v in p.items() if k not in ("members", "links")} for p in d["patterns"]])
    _write_csv(out / "pattern_members.csv", [{"pattern_id": p["pattern_id"], "pattern_label": p["label"], **m} for p in d["patterns"] for m in p["members"]])
    _write_csv(out / "events.csv", d["events"])
    for name in ("by_sector", "by_region", "by_fy", "by_country"):
        _write_csv(out / f"{name}.csv", d[name])
    d["result"] = result
    note = str(out)
    if ctx.cfg("classify", {}).get("write_back", True):
        n = _write_back(ctx)
        note += f"; {n} rows of replication_label / scaling_label written to the database"
    ctx.log("write", note=note)


def _write_back(ctx: PatternContext) -> int:
    """Two columns into approaches: replication_label ('confirmed: P123456 - name' / 'likely: ...') and scaling_label."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(ctx.db_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(approaches)")}
    for col in ("replication_label", "scaling_label", "pattern_run"):
        if col not in cols:
            con.execute(f"ALTER TABLE approaches ADD COLUMN {col} TEXT")
    con.execute("UPDATE approaches SET replication_label='', scaling_label='', pattern_run=?", (ctx.out_dir.name,))
    n = 0
    for r in ctx.data["approach_rows"]:
        rep = f"{r['replication']}: {r['replication_source_project'] or r['replication_source_text'] or 'source not identified'}" if r["replication"] else ""
        if r["replication"] and r["replication_source_name"]:
            rep += f" - {r['replication_source_name']}"
        sc = f"scaling: {r['scaling_source_project']} - {r['scaling_source_name']}" if r["scaling"] else ""
        con.execute("UPDATE approaches SET replication_label=?, scaling_label=?, pattern_run=? WHERE approach_id=?", (rep, sc, ctx.out_dir.name, r["approach_id"]))
        n += bool(rep or sc)
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('patterns_last_write', ?)", (stamp,))
    con.commit(); con.close()
    return n
