"""Workflow v2 - DDAT sentence coding (Methodology Notes 1 & 2)."""
from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor

from ...documents import DocumentRef, read_text
from ...models import Approach, Attribute, Evidence
from ...segment import Sentence, context, segment
from ...semantic import SemanticMatcher
from ...taxonomy import ddat, innovation_keywords
from ..base import RunContext
from ..v1.steps import step_screen  # keyword tier, kept for information

LEVEL_RANK = {"L1": 1, "L2": 2, "L3": 3}
_matcher_cache: dict[str, SemanticMatcher] = {}


def run(ctx: RunContext) -> None:
    for name in ctx.cfg("steps"):
        globals()[f"step_{name}"](ctx)
        if ctx.record.error:
            break


# ----------------------------------------------------------------------------
def step_select_documents(ctx: RunContext) -> None:
    t = ctx.step("select_documents")
    rules = ctx.cfg("documents", {})
    docs = ctx.index.for_project(ctx.project.project_id)
    chosen: list[DocumentRef] = []
    for dtype in rules.get("include_types", []):
        cands = sorted([d for d in docs if d.doc_type == dtype], key=lambda d: d.doc_date)
        cap = rules.get("max_per_type", {}).get(dtype)
        chosen.extend(cands[-cap:] if cap else cands)
    ctx.docs = chosen
    ctx.record.documents_used = [{**d.to_dict(), "role": "primary" if d.doc_type in ("PAD", "ProjectPaper", "PID", "ProgramDocument") else "supporting"} for d in chosen]
    ctx.finish(t, note=", ".join(f"{d.doc_type} {d.doc_date}" for d in chosen) or "none", selected=ctx.record.documents_used)


def step_segment(ctx: RunContext) -> None:
    t = ctx.step("segment")
    ctx.sentences = {}
    n, flagged = 0, 0
    for d in ctx.docs:
        sents = segment(d)
        ctx.sentences[d.guid] = sents
        n += len(sents)
        flagged += sum(1 for s in sents if s.boilerplate)
    ctx.finish(t, note=f"{n} sentences in {len(ctx.docs)} documents ({flagged} flagged as boilerplate)", sentences=n, boilerplate=flagged)


def _matcher(ctx: RunContext) -> SemanticMatcher:
    cfg = ctx.cfg("candidates", {})
    key = cfg.get("semantic_backend", "auto")
    with (ctx.lock if ctx.lock is not None else contextlib.nullcontext()):
        if key not in _matcher_cache:
            _matcher_cache[key] = SemanticMatcher.build(key, cfg.get("semantic_threshold_embedding", 0.45), cfg.get("semantic_threshold_tfidf", 0.2))
        return _matcher_cache[key]


def step_candidates(ctx: RunContext) -> None:
    t = ctx.step("candidates")
    cfg = ctx.cfg("candidates", {})
    matcher = _matcher(ctx)
    cands: list[dict] = []
    pool: list[tuple[Sentence, int]] = []
    for d in ctx.docs:
        for i, s in enumerate(ctx.sentences[d.guid]):
            if cfg.get("drop_boilerplate", True) and s.boilerplate:
                continue
            pool.append((s, i))
    kw = [ddat.keyword_hits(s.text) for s, _ in pool]
    sem = matcher.candidates([s.text for s, _ in pool])
    for (s, i), k, m in zip(pool, kw, sem):
        if not k and not m:
            continue
        codes = sorted(set(k) | set(m), key=lambda c: -(m.get(c, 0) + (0.5 if c in k else 0)))
        route = "both" if k and m else ("keyword" if k else "semantic")
        score = max(m.values(), default=0.0) + (0.5 if k else 0)
        before, after = context(ctx.sentences[s.doc.guid], i)
        cands.append({"sentence": s, "codes": codes, "route": route, "keywords": sorted({w for ws in k.values() for w in ws}),
                      "semantic": m, "score": score, "before": before, "after": after})
    cap = cfg.get("max_candidates_per_project", 400)
    dropped = 0
    if len(cands) > cap:
        cands.sort(key=lambda c: -c["score"])
        dropped = len(cands) - cap
        cands = cands[:cap]
    cands.sort(key=lambda c: (c["sentence"].doc.guid, c["sentence"].position))
    ctx.candidates = cands
    routes = {"keyword": 0, "semantic": 0, "both": 0}
    for c in cands:
        routes[c["route"]] += 1
    ctx.finish(t, note=f"{len(cands)} candidate sentences ({routes['keyword']} keyword, {routes['semantic']} semantic, {routes['both']} both); backend {matcher.backend}",
               candidates=len(cands), routes=routes, backend=matcher.backend, dropped_over_cap=dropped)


# ----------------------------------------------------------------------------
def _candidate_block(cands: list[dict], offset: int) -> str:
    lines = []
    for j, c in enumerate(cands):
        s = c["sentence"]
        lines.append(f"[C{offset + j}] (candidates: {', '.join(c['codes'][:4])}) doc={s.doc.doc_type} {s.doc.doc_date} pos={s.position} route={c['route']}"
                     f"\n  BEFORE: {c['before'][:300]}\n  SENTENCE: {s.text}\n  AFTER: {c['after'][:300]}")
    return "\n\n".join(lines)


def step_classify(ctx: RunContext) -> None:
    t = ctx.step("classify")
    cfg = ctx.cfg("classify", {})
    p = ctx.project
    cands = ctx.candidates
    if not cands:
        ctx.record.innovative = "No"
        ctx.finish(t, "skipped", "no candidate sentences")
        return
    system = ctx.workflow.prompt("00_system", taxonomy=ddat.taxonomy_prompt_text(True))
    bs = cfg.get("batch_size", 20)
    batches = [(i, cands[i:i + bs]) for i in range(0, len(cands), bs)]

    def run_batch(item):
        off, chunk = item
        prompt = ctx.workflow.prompt("01_classify", project_id=p.project_id, project_name=p.project_name, country=p.country,
                                     lead_practice=p.lead_practice, approval_date=p.approval_date, candidates=_candidate_block(chunk, off))
        data = ctx.llm.complete_json("classify", system, prompt, cache_system=cfg.get("cache_taxonomy", True))
        return off, chunk, data

    results = []
    with ThreadPoolExecutor(max_workers=max(1, cfg.get("parallel_batches", 4))) as ex:
        for off, chunk, data in ex.map(run_batch, batches):
            results.append((off, chunk, data))
    rows, excluded = [], []
    valid = set(ddat.approaches())
    for off, chunk, data in results:
        by_id = {str(r.get("candidate_id", "")).strip(): r for r in data.get("results", []) if isinstance(r, dict)}
        for j, c in enumerate(chunk):
            s = c["sentence"]
            r = by_id.get(f"C{off + j}")
            matches = [m for m in (r or {}).get("matches", []) if isinstance(m, dict) and str(m.get("code", "")).strip() in valid]
            if not matches:
                excluded.append({"guid": s.doc.guid, "doc_type": s.doc.doc_type, "position": s.position, "char_start": s.start, "char_end": s.end,
                                 "sentence": s.text, "candidate_codes": c["codes"], "route": c["route"],
                                 "reason": (r or {}).get("excluded_reason", "") or ("no answer from model" if r is None else "no match")})
                continue
            bundle = f"B-{p.project_id}-{s.doc.guid[-6:]}-{s.position}" if len(matches) > 1 else ""
            codes_here = [str(m["code"]).strip() for m in matches]
            for m in matches:
                code = str(m["code"]).strip()
                lvl = str(m.get("evidence_level", "L2")).upper().strip()
                lvl = lvl if lvl in LEVEL_RANK else "L2"
                a = ddat.approaches()[code]
                rows.append({
                    "row_id": f"R-{p.project_id}-{s.doc.guid[-6:]}-{s.position}-{code}", "bundle_id": bundle,
                    "bundled_with": ";".join(x for x in codes_here if x != code), "project_id": p.project_id,
                    "doc_id": s.doc.guid, "doc_type": s.doc.doc_type, "doc_date": s.doc.doc_date, "file_name": s.doc.file_name,
                    "sentence_position": s.position, "char_start": s.start, "char_end": s.end,
                    "approach_code": code, "approach_name": a.name, "parent_theme": a.parent_code, "parent_theme_name": a.parent_name,
                    "sentence": s.text, "context_before": c["before"], "context_after": c["after"],
                    "match_route": c["route"], "keywords_hit": ";".join(c["keywords"]), "semantic_score": c["semantic"].get(code),
                    "evidence_level": lvl, "status": str(m.get("status", "")).lower().strip(), "reason": str(m.get("reason", "")).strip(),
                    "solution": "", "pillar": "", "solution_reason": "",
                    "workflow_version": ctx.workflow.version, "run_id": ctx.record.run_id, "review_status": "", "reviewer_note": "",
                })
    ctx.record.aec_rows = rows
    ctx.record.exclusion_log = excluded
    ctx.finish(t, note=f"{len(rows)} coded rows from {len(cands)} candidates; {len(excluded)} excluded; {len(batches)} LLM calls",
               rows=len(rows), excluded=len(excluded), calls=len(batches))


# ----------------------------------------------------------------------------
def step_aggregate(ctx: RunContext) -> None:
    """AEC rows -> one project-level Approach per DDAT code (highest evidence level)."""
    t = ctx.step("aggregate")
    p = ctx.project
    cfg = ctx.cfg("aggregation", {})
    headline = set(cfg.get("headline_levels", ["L2", "L3"]))
    by_code: dict[str, list[dict]] = {}
    for r in ctx.record.aec_rows:
        by_code.setdefault(r["approach_code"], []).append(r)
    doc_pref = {"PAD": 0, "ProjectPaper": 1, "ProgramDocument": 1, "PID": 2, "ICR": 3, "ISR": 4}
    for code, rows in sorted(by_code.items()):
        rows.sort(key=lambda r: (-LEVEL_RANK[r["evidence_level"]], doc_pref.get(r["doc_type"], 9), r["doc_date"], r["sentence_position"]))
        best = rows[0]
        a = ddat.approaches()[code]
        top = best["evidence_level"]
        ev = Evidence(best["doc_id"], best["doc_type"], best["doc_date"], best["file_name"], best["char_start"], best["char_end"], best["sentence"], "exact", 1.0)
        extra = [Evidence(r["doc_id"], r["doc_type"], r["doc_date"], r["file_name"], r["char_start"], r["char_end"], r["sentence"], "exact", 1.0)
                 for r in rows[1:cfg.get("max_rows_per_approach_kept", 8)]]
        levels = {lvl: sum(1 for r in rows if r["evidence_level"] == lvl) for lvl in ("L1", "L2", "L3")}
        ap = Approach(
            approach_id=f"{p.project_id}-{code}", project_id=p.project_id, name=f"{code} {a.name}",
            description=f"{len(rows)} coded sentence(s): L1 {levels['L1']}, L2 {levels['L2']}, L3 {levels['L3']}. Best row: {best['reason']}",
            evidence=ev, why_innovative=f"evidence level {top}; status {best['status'] or 'n/a'}; route {best['match_route']}",
            extra_evidence=extra, status="validated" if top in headline else "referenced_only")
        ap.theme = Attribute(f"{a.parent_code} {a.parent_name}", a.parent_code, 1.0, "parent theme of the DDAT approach", "confirmed")
        lead = p.sectors[0].name if p.sectors else ""
        ap.sector = Attribute(lead, "", 1.0, "lead sector from projects.csv (sector is a project attribute, Note 1)", "confirmed")
        ap.category = Attribute("", "", None, "")
        ap.category_solution = Attribute("", "", None, "")
        ctx.record.approaches.append(ap)
    live = [a for a in ctx.record.approaches if a.status == "validated"]
    ctx.record.innovative = "Yes" if live else ("Unclear" if ctx.record.approaches else "No")
    ctx.finish(t, note=f"{len(ctx.record.approaches)} approaches ({len(live)} at L2/L3)", approaches=len(ctx.record.approaches), headline=len(live))


# ----------------------------------------------------------------------------
def step_map_solutions(ctx: RunContext) -> None:
    """Note 2: approach -> solution (direct or model choice) -> pillar."""
    t = ctx.step("solution")
    p = ctx.project
    rows_by_code: dict[str, list[dict]] = {}
    for r in ctx.record.aec_rows:
        rows_by_code.setdefault(r["approach_code"], []).append(r)
    n_model, n_direct = 0, 0

    def choose(ap: Approach):
        code = ap.approach_id.split("-")[-1]
        cands, rule = ddat.solution_candidates(code)
        if not cands:
            return ap, "Unmapped", "no candidate solutions", rule
        if len(cands) == 1:
            return ap, cands[0], "single candidate (direct mapping)", rule
        best = ap.evidence
        try:
            data = ctx.llm.complete_json("solution", "You map World Bank project activities to the Digital & AI Implementation Plan. Answer with JSON only.",
                                     ctx.workflow.prompt("02_solution", project_id=p.project_id, project_name=p.project_name, approach_code=code,
                                                         approach_name=ddat.approaches()[code].name, doc_type=best.doc_type, doc_date=best.doc_date,
                                                         sentence=best.text, before=_ctx_of(rows_by_code[code][0], "context_before"),
                                                         after=_ctx_of(rows_by_code[code][0], "context_after"), candidate_codes=", ".join(cands),
                                                         solution_text=ddat.solution_prompt_text(cands)), retries=2)
        except Exception as e:  # keep the row; the reviewer can map it by hand
            return ap, "Unmapped", f"model error: {type(e).__name__}", rule
        sol = str(data.get("solution", "Unmapped")).upper().strip()
        return ap, (sol if sol in cands else "Unmapped"), str(data.get("reason", "")), rule

    with ThreadPoolExecutor(max_workers=4) as ex:
        for ap, sol, reason, rule in ex.map(choose, ctx.record.approaches):
            if rule == "model_choice":
                n_model += 1
            else:
                n_direct += 1
            pillar_code, pillar_name = ddat.pillar_for(sol) if sol != "Unmapped" else ("", "")
            ap.category_solution = Attribute(ddat.solution_title(sol) if sol != "Unmapped" else "Unmapped", sol if sol != "Unmapped" else "", 1.0 if rule == "direct" else 0.7, reason, "confirmed")
            ap.category = Attribute(pillar_name or ("Trust, Safety, and Security (cross-cutting)" if sol == "TRUST" else "Unmapped"), pillar_code, 1.0 if rule == "direct" else 0.7, f"pillar of {sol}", "confirmed")
            code = ap.approach_id.split("-")[-1]
            for r in rows_by_code.get(code, []):
                r["solution"], r["pillar"], r["solution_reason"] = sol, pillar_code or ("TRUST" if sol == "TRUST" else ""), reason
    ctx.finish(t, note=f"{n_direct} direct, {n_model} model-chosen solution mappings")


def _ctx_of(row: dict, key: str) -> str:
    return (row.get(key) or "")[:400]


# ----------------------------------------------------------------------------
def step_replication(ctx: RunContext) -> None:
    t = ctx.step("replication")
    rc = ctx.cfg("replication", {})
    p = ctx.project
    store = ctx.portfolio
    live = [a for a in ctx.record.approaches if a.status == "validated"]
    explicit = []
    if rc.get("explicit_reference", True):
        full = "\n".join(read_text(d.path) for d in ctx.index.for_project(p.project_id))
        explicit = store.explicit_references(p.project_id, full)
    n_sim = 0
    with (ctx.lock if ctx.lock is not None else contextlib.nullcontext()):
        for a in live:
            text = f"{a.name}. {a.description} {a.evidence.text} " + " ".join(e.text for e in a.extra_evidence[:3])
            links = list(explicit)
            if rc.get("similarity", True):
                sim = store.similar_approaches(a.approach_id, p.project_id, text, rc.get("similarity_threshold", 0.3), rc.get("max_links", 5))
                n_sim += len(sim)
                links.extend(sim)
            a.replication = links
            store.upsert(a.approach_id, p.project_id, p.approval_date, a.name, text)
        store.save()
    ctx.finish(t, note=f"{len(explicit)} explicit references, {n_sim} similar approaches", explicit=[l.to_dict() for l in explicit], store_size=len(store.approaches))
