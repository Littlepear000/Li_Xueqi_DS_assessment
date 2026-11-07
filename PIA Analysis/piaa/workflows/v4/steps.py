"""Workflow v4 - digital/AI innovation approaches by (category, sector, theme)."""
from __future__ import annotations

import collections
from concurrent.futures import ThreadPoolExecutor

from ...models import Approach, Attribute, Evidence
from ...segment import context
from ...taxonomy import ddat, innovation_keywords, innovation_types
from ..base import RunContext
from ...examples import with_examples as _with_examples
from ..v1.steps import _match_name
from ..v2.steps import step_replication, step_screen, step_segment, step_select_documents  # noqa: F401

CATEGORIES = list(innovation_types.CATEGORIES)
ADOPTION_RANK = {"apply": 3, "prospect": 2, "discuss": 1}
DOC_PREF = {"PAD": 0, "ProjectPaper": 1, "ProgramDocument": 1, "PID": 2, "ICR": 3, "ISR": 4}


def run(ctx: RunContext) -> None:
    for name in ctx.cfg("steps"):
        globals()[f"step_{name}"](ctx)
        if ctx.record.error:
            break


# ----------------------------------------------------------------------------
def step_candidates(ctx: RunContext) -> None:
    """Digital / data / AI cue filter: DDAT keyword lists + enabling-technology terms."""
    t = ctx.step("candidates")
    cfg = ctx.cfg("candidates", {})
    tech = [p for p in innovation_keywords.PATTERNS if p.dimension == "enabling_technologies"]
    cands = []
    for d in ctx.docs:
        sents = ctx.sentences[d.guid]
        for i, s in enumerate(sents):
            if cfg.get("drop_boilerplate", True) and s.boilerplate:
                continue
            hits = ddat.keyword_hits(s.text)
            terms = sorted({w for ws in hits.values() for w in ws})
            terms += [p.term for p in tech if p.regex.search(s.text) and p.term not in terms]
            if not terms:
                continue
            before, after = context(sents, i)
            cands.append({"sentence": s, "keywords": terms, "score": len(terms), "before": before, "after": after})
    cap = cfg.get("max_candidates_per_project", 400)
    dropped = 0
    if len(cands) > cap:
        cands.sort(key=lambda c: -c["score"])
        dropped = len(cands) - cap
        cands = cands[:cap]
    cands.sort(key=lambda c: (c["sentence"].doc.guid, c["sentence"].position))
    ctx.candidates = cands
    ctx.finish(t, note=f"{len(cands)} candidate sentences with a digital / AI cue", candidates=len(cands), dropped_over_cap=dropped)


def _candidate_block(cands, offset):
    out = []
    for j, c in enumerate(cands):
        s = c["sentence"]
        out.append(f"[C{offset + j}] doc={s.doc.doc_type} {s.doc.doc_date} pos={s.position} cues={', '.join(c['keywords'][:5])}"
                   f"\n  BEFORE: {c['before'][:300]}\n  SENTENCE: {s.text}\n  AFTER: {c['after'][:300]}")
    return "\n\n".join(out)


def step_classify(ctx: RunContext) -> None:
    t = ctx.step("classify")
    cfg = ctx.cfg("classify", {})
    p = ctx.project
    cands = ctx.candidates
    if not cands:
        ctx.record.innovative = "No"
        ctx.finish(t, "skipped", "no candidate sentences")
        return
    system = ctx.workflow.prompt("00_system", taxonomy=innovation_types.prompt_text())
    system = _with_examples(ctx, t, system)   # reviewer-curated good / bad examples (Setup page)
    bs = cfg.get("batch_size", 20)
    batches = [(i, cands[i:i + bs]) for i in range(0, len(cands), bs)]

    def run_batch(item):
        off, chunk = item
        prompt = ctx.workflow.prompt("01_classify", project_id=p.project_id, project_name=p.project_name, country=p.country,
                                     lead_practice=p.lead_practice, approval_date=p.approval_date, candidates=_candidate_block(chunk, off))
        try:
            data = ctx.llm.complete_json("classify", system, prompt, retries=2, cache_system=cfg.get("cache_system", True))
        except Exception as e:
            data = {"results": [], "error": f"{type(e).__name__}: {str(e)[:200]}"}
        return off, chunk, data

    passages, excluded, errors, last_error = [], [], 0, ""
    with ThreadPoolExecutor(max_workers=max(1, cfg.get("parallel_batches", 6))) as ex:
        for off, chunk, data in ex.map(run_batch, batches):
            if data.get("error"):
                errors += 1
                last_error = data["error"]
                continue  # a failed batch is NOT an exclusion; the run is marked as failed below
            by_id = {str(r.get("candidate_id", "")).strip(): r for r in data.get("results", []) if isinstance(r, dict)}
            for j, c in enumerate(chunk):
                s = c["sentence"]
                r = by_id.get(f"C{off + j}")
                matches = [m for m in (r or {}).get("matches", []) if isinstance(m, dict) and str(m.get("category", "")).strip().capitalize() in CATEGORIES]
                if not matches:
                    excluded.append({"guid": s.doc.guid, "doc_type": s.doc.doc_type, "position": s.position, "char_start": s.start, "char_end": s.end,
                                     "sentence": s.text, "candidate_codes": c["keywords"][:5], "route": "keyword",
                                     "reason": (r or {}).get("excluded_reason", "") or ("no answer from model" if r is None else "no match")})
                    continue
                for m in matches:
                    adoption = str(m.get("adoption", "discuss")).lower().strip()
                    adoption = adoption if adoption in ADOPTION_RANK else "discuss"
                    passages.append({
                        "passage_id": f"P{len(passages) + 1}", "project_id": p.project_id,
                        "doc_id": s.doc.guid, "doc_type": s.doc.doc_type, "doc_date": s.doc.doc_date, "file_name": s.doc.file_name,
                        "sentence_position": s.position, "char_start": s.start, "char_end": s.end,
                        "sentence": s.text, "context_before": c["before"], "context_after": c["after"], "keywords_hit": ";".join(c["keywords"]),
                        "category": str(m.get("category")).strip().capitalize(), "adoption": adoption,
                        "label": str(m.get("label", "")).strip(), "reason": str(m.get("reason", "")).strip(),
                        "sector": "", "theme": "", "code_reason": "",
                        "workflow_version": ctx.workflow.version, "run_id": ctx.record.run_id,
                    })
    ctx.passages = passages
    ctx.record.exclusion_log = excluded
    if errors:
        ctx.record.error = f"classify: {errors} of {len(batches)} batches failed ({last_error})"
        ctx.finish(t, "failed", f"{errors} of {len(batches)} LLM batches failed: {last_error}")
        return
    ctx.finish(t, note=f"{len(passages)} coded passages from {len(cands)} candidates; {len(excluded)} excluded; {len(batches)} LLM calls" + (f"; {errors} failed batches" if errors else ""),
               passages=len(passages), excluded=len(excluded), calls=len(batches), failed_batches=errors)


# ----------------------------------------------------------------------------
def _options(shares):
    return "\n".join(f"- {s.name} ({s.pct:g}%)" if s.pct is not None else f"- {s.name}" for s in shares) or "- (none listed)"


def step_codes(ctx: RunContext) -> None:
    """One sector and one theme per coded passage, from the project's own lists."""
    t = ctx.step("codes")
    cfg = ctx.cfg("codes", {})
    p = ctx.project
    passages = getattr(ctx, "passages", [])
    if not passages:
        ctx.finish(t, "skipped", "no coded passages")
        return
    lead_sector = p.sectors[0].name if p.sectors else ""
    lead_theme = p.themes[0].name if p.themes else ""
    if len(p.sectors) <= 1 and len(p.themes) <= 1:
        for ps in passages:
            ps["sector"], ps["theme"], ps["code_reason"] = lead_sector, lead_theme, "single option in projects.csv"
        ctx.finish(t, note="single sector / theme option: assigned directly")
        return
    bs = cfg.get("batch_size", 30)
    batches = [passages[i:i + bs] for i in range(0, len(passages), bs)]

    def run_batch(chunk):
        block = "\n\n".join(f"[{ps['passage_id']}] ({ps['category']}; {ps['label']}) {ps['sentence']}" for ps in chunk)
        prompt = ctx.workflow.prompt("02_codes", project_id=p.project_id, project_name=p.project_name, country=p.country, lead_practice=p.lead_practice,
                                     sector_options=_options(p.sectors), theme_options=_options(p.themes), passages=block)
        try:
            return chunk, ctx.llm.complete_json("codes", "You assign World Bank sector and theme codes. Answer with JSON only.", prompt, retries=2)
        except Exception as e:
            return chunk, {"results": [], "error": f"{type(e).__name__}: {str(e)[:200]}"}

    n_ok, errs = 0, []
    with ThreadPoolExecutor(max_workers=max(1, cfg.get("parallel_batches", 4))) as ex:
        for chunk, data in ex.map(run_batch, batches):
            if data.get("error"):
                errs.append(data["error"])
            by_id = {str(r.get("passage_id", "")).strip(): r for r in data.get("results", []) if isinstance(r, dict)}
            for ps in chunk:
                r = by_id.get(ps["passage_id"])
                if r:
                    ps["sector"] = _match_name(r.get("sector", ""), p.sectors) or lead_sector
                    ps["theme"] = _match_name(r.get("theme", ""), p.themes) or lead_theme
                    ps["code_reason"] = str(r.get("reason", ""))
                    n_ok += 1
                else:
                    ps["sector"], ps["theme"], ps["code_reason"] = lead_sector, lead_theme, "fallback: lead sector / theme (no answer)"
    if errs:
        ctx.record.error = f"codes: {len(errs)} of {len(batches)} batches failed ({errs[0]})"
        ctx.finish(t, "failed", ctx.record.error)
        return
    ctx.finish(t, note=f"{n_ok} of {len(passages)} passages assigned by the model; {len(batches)} LLM calls")


# ----------------------------------------------------------------------------
def step_aggregate(ctx: RunContext) -> None:
    """Same (category, sector, theme) = one approach; keep every passage as evidence."""
    t = ctx.step("aggregate")
    cfg = ctx.cfg("aggregation", {})
    p = ctx.project
    passages = getattr(ctx, "passages", [])
    groups: dict[tuple, list[dict]] = collections.OrderedDict()
    for ps in passages:
        groups.setdefault((ps["category"], ps["sector"], ps["theme"]), []).append(ps)
    headline = set(cfg.get("headline_adoption", ["apply"]))
    rows = []
    for n, ((cat, sec, th), evs) in enumerate(groups.items(), 1):
        evs.sort(key=lambda r: (-ADOPTION_RANK[r["adoption"]], DOC_PREF.get(r["doc_type"], 9), r["doc_date"], r["sentence_position"]))
        best = evs[0]
        adoption = max((e["adoption"] for e in evs), key=lambda a: ADOPTION_RANK[a])
        label = collections.Counter(e["label"] for e in evs if e["label"]).most_common(1)
        label = label[0][0] if label else best["label"]
        aid = f"{p.project_id}-A{n}"
        counts = collections.Counter(e["adoption"] for e in evs)
        mk = lambda e: Evidence(e["doc_id"], e["doc_type"], e["doc_date"], e["file_name"], e["char_start"], e["char_end"], e["sentence"], "exact", 1.0)
        ap = Approach(
            approach_id=aid, project_id=p.project_id, name=f"{cat} · {label}",
            description=f"{len(evs)} evidence passage(s): apply {counts.get('apply', 0)}, prospect {counts.get('prospect', 0)}, discuss {counts.get('discuss', 0)}. {best['reason']}",
            evidence=mk(best), why_innovative=f"category {cat}; adoption {adoption}; sector {sec}; theme {th}",
            extra_evidence=[mk(e) for e in evs[1:cfg.get("max_evidence_kept", 20)]],
            status="validated" if adoption in headline else "mentioned_only")
        ap.category = Attribute(cat, cat[:4].upper(), None, "working-paper innovation category (v4 definition)", "confirmed")
        ap.category_solution = Attribute("", "", None, "")
        ap.sector = Attribute(sec, "", None, best.get("code_reason", ""), "confirmed")
        ap.theme = Attribute(th, "", None, best.get("code_reason", ""), "confirmed")
        ap.adoption = Attribute(adoption, "", None, best["reason"], "confirmed")
        ctx.record.approaches.append(ap)
        for k, e in enumerate(evs, 1):
            rows.append({"row_id": f"{aid}-E{k}", "approach_id": aid, "evidence_no": k, "number_of_evidence": len(evs), **{kk: vv for kk, vv in e.items() if kk != "passage_id"}})
    ctx.record.aec_rows = rows
    live = [a for a in ctx.record.approaches if a.status == "validated"]
    ctx.record.innovative = "Yes" if live else ("Unclear" if ctx.record.approaches else "No")
    ctx.finish(t, note=f"{len(ctx.record.approaches)} approaches ({len(live)} applied) from {len(passages)} passages", approaches=len(ctx.record.approaches), applied=len(live))
