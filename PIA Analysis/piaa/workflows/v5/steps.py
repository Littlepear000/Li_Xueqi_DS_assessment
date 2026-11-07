"""Workflow v5 - practice extraction from the PAD with reading units, a judge and context expansion.

Pipeline (see config.yaml ``steps``)::

    locate_pad -> units -> candidates -> extract -> validate -> codes -> merge -> aggregate -> replication

* ``extract`` reads candidate units in small batches and returns practices with
  evidence *sentence ids*; the sentences are resolved in Python, so evidence is
  verbatim and anchored by construction.
* ``validate`` judges every extracted practice; when the judge answers
  ``expand`` the unit is widened by ``expand_chars`` on each side and judged
  again (``03_revalidate``).
* Rejected practices go to the exclusion log with the judge's reason, so the
  workflow can be tuned from the results.
"""
from __future__ import annotations

import collections
from concurrent.futures import ThreadPoolExecutor

from ...models import Approach, Attribute, Evidence
from ...documents import read_text
from ...segment import segment
from ...taxonomy import ddat, innovation_keywords, innovation_types
from ...units import build_units, expand
from ..base import RunContext
from ...examples import with_examples as _with_examples
from ..v1.steps import _match_name
from ..v2.steps import step_replication  # noqa: F401  (portfolio-level, unchanged)

CATEGORIES = list(innovation_types.CATEGORIES)
ADOPTION_RANK = {"apply": 3, "prospect": 2, "discuss": 1}


def run(ctx: RunContext) -> None:
    for name in ctx.cfg("steps"):
        globals()[f"step_{name}"](ctx)
        if ctx.record.error:
            break


def _norm_category(v) -> str:
    v = str(v or "").strip().capitalize()
    return v if v in CATEGORIES else ""


def _norm_adoption(v) -> str:
    v = str(v or "").strip().lower()
    return v if v in ADOPTION_RANK else ""


def _pmap(fn, items, workers):
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(fn, items))


# ----------------------------------------------------------------------------
def step_locate_pad(ctx: RunContext) -> None:
    """The project's primary document: newest PAD, else the first fallback type that exists."""
    t = ctx.step("locate_pad")
    cfg = ctx.cfg("documents", {})
    docs = ctx.index.for_project(ctx.project.project_id)
    chosen, skipped = None, []
    for dtype in cfg.get("priority", ["PAD"]):
        for d in sorted([d for d in docs if d.doc_type == dtype], key=lambda d: d.doc_date, reverse=True):
            share = _latin_share(read_text(d.path))
            if share < cfg.get("min_latin_share", 0.7):      # e.g. an Arabic or Russian PAD: not readable by the English prompts
                skipped.append(f"{d.file_name} (latin share {share:.2f})")
                continue
            chosen = d
            break
        if chosen:
            break
    if chosen is None:
        ctx.record.error = "no readable PAD (or fallback document) for this project" + (f"; skipped: {'; '.join(skipped)}" if skipped else "")
        ctx.record.innovative = "Unclear"
        ctx.finish(t, "failed", ctx.record.error)
        return
    ctx.docs = [chosen]
    ctx.record.documents_used = [{**chosen.to_dict(), "role": "primary"}]
    ctx.finish(t, note=f"{chosen.doc_type} {chosen.doc_date} ({chosen.file_name})" + (f"; skipped non-Latin: {'; '.join(skipped)}" if skipped else ""),
               selected=ctx.record.documents_used, skipped=skipped)


def _latin_share(text: str) -> float:
    alpha = sum(1 for ch in text if ch.isalpha())
    latin = sum(1 for ch in text if ch.isalpha() and ch.isascii())
    return latin / alpha if alpha else 1.0


def step_units(ctx: RunContext) -> None:
    t = ctx.step("units")
    cfg = ctx.cfg("units", {})
    doc = ctx.docs[0]
    sents = segment(doc)
    ctx.sentences = {doc.guid: sents}
    ctx.units = build_units(doc, cfg.get("target_chars", 1200), cfg.get("max_chars", 2400), cfg.get("min_chars", 250), sentences=sents)
    numbered = sum(1 for u in ctx.units if u.para_no is not None)
    ctx.finish(t, note=f"{len(ctx.units)} reading units ({numbered} numbered paragraphs) from {len(sents)} sentences",
               units=len(ctx.units), numbered=numbered, sentences=len(sents))


def step_candidates(ctx: RunContext) -> None:
    """Units that carry a digital / data / AI cue (same dictionary as v4, applied per unit)."""
    t = ctx.step("candidates")
    cfg = ctx.cfg("candidates", {})
    tech = [p for p in innovation_keywords.PATTERNS if p.dimension == "enabling_technologies"]
    kept = []
    for u in ctx.units:
        if cfg.get("drop_boilerplate", True) and u.boilerplate:
            continue
        text = u.text
        hits = ddat.keyword_hits(text)
        terms = sorted({w for ws in hits.values() for w in ws})
        terms += [p.term for p in tech if p.regex.search(text) and p.term not in terms]
        u.cues = terms
        if terms or not cfg.get("require_cue", True):
            kept.append(u)
    cap = cfg.get("max_units_per_project", 150)
    dropped = 0
    if len(kept) > cap:
        kept.sort(key=lambda u: -len(u.cues) / max(1, u.chars))
        dropped = len(kept) - cap
        kept = sorted(kept[:cap], key=lambda u: u.index)
    ctx.candidates = kept
    ctx.finish(t, note=f"{len(kept)} of {len(ctx.units)} units carry a digital / AI cue" + (f"; {dropped} dropped over the cap" if dropped else ""),
               candidate_units=len(kept), dropped=dropped)


# ----------------------------------------------------------------------------
def _project_fields(p):
    return dict(project_id=p.project_id, project_name=p.project_name, country=p.country, lead_practice=p.lead_practice, approval_date=p.approval_date)


def step_extract(ctx: RunContext) -> None:
    t = ctx.step("extract")
    cfg = ctx.cfg("extract", {})
    p = ctx.project
    units = ctx.candidates
    if not units:
        ctx.record.innovative = "No"
        ctx.finish(t, "skipped", "no candidate units")
        return
    system = ctx.workflow.prompt("00_system", taxonomy=innovation_types.prompt_text())
    system = _with_examples(ctx, t, system)   # reviewer-curated good / bad examples (Setup page)
    by_id = {u.unit_id: u for u in units}
    bs = cfg.get("units_per_call", 6)
    batches = [units[i:i + bs] for i in range(0, len(units), bs)]
    max_ev = cfg.get("max_evidence_per_approach", 3)

    def call(chunk):
        block = "\n\n".join(f"--- {u.unit_id} (doc={u.doc.doc_type} {u.doc.doc_date}; para {u.para_no if u.para_no else '-'}; cues: {', '.join(u.cues[:6])})\n{u.numbered_text()}" for u in chunk)
        prompt = ctx.workflow.prompt("01_extract", **_project_fields(p), max_evidence=max_ev, units=block)
        try:
            return chunk, ctx.llm.complete_json("extract", system, prompt, retries=2, cache_system=cfg.get("cache_system", True))
        except Exception as e:
            return chunk, {"error": f"{type(e).__name__}: {str(e)[:200]}"}

    found, errors, last_error, unresolved = [], 0, "", 0
    for chunk, data in _pmap(call, batches, cfg.get("parallel_calls", 4)):
        if data.get("error"):
            errors += 1
            last_error = data["error"]
            continue
        for ur in data.get("units", []) or []:
            u = by_id.get(str(ur.get("unit_id", "")).strip())
            if u is None:
                continue
            for a in ur.get("approaches", []) or []:
                if not isinstance(a, dict):
                    continue
                cat, adoption = _norm_category(a.get("category")), _norm_adoption(a.get("adoption"))
                sents = [s for s in (u.sentence(r) for r in (a.get("evidence") or [])[:max_ev]) if s is not None]
                if not sents or not cat:
                    unresolved += 1
                    continue
                if not adoption:
                    adoption = "discuss"
                found.append({
                    "approach_id": f"A{len(found) + 1}", "unit": u, "practice": str(a.get("practice", "")).strip(),
                    "what_is_done": str(a.get("what_is_done", "")).strip(), "category": cat, "adoption": adoption,
                    "evidence": sents, "reason": str(a.get("reason", "")).strip(), "rounds": [],
                })
    ctx.extracted = found
    if errors:
        ctx.record.error = f"extract: {errors} of {len(batches)} calls failed ({last_error})"
        ctx.finish(t, "failed", ctx.record.error)
        return
    ctx.finish(t, note=f"{len(found)} candidate practices from {len(units)} units in {len(batches)} calls" + (f"; {unresolved} dropped (unresolvable evidence id or category)" if unresolved else ""),
               extracted=len(found), calls=len(batches), unresolved=unresolved)


# ----------------------------------------------------------------------------
def _approach_block(a, text):
    ev = ", ".join(f"[{a['unit'].unit_id}.s{a['unit'].sentences.index(s) + 1}]" for s in a["evidence"])
    return (f"--- {a['approach_id']}\npractice: {a['practice']}\nwhat_is_done: {a['what_is_done']}\ncategory: {a['category']}; adoption: {a['adoption']}\n"
            f"evidence sentences: {ev}\nextractor's reason: {a['reason']}\n{text}")


def _apply_verdict(a, r, round_no, context_chars):
    verdict = str(r.get("verdict", "")).strip().lower()
    reason = str(r.get("reason", "")).strip()
    a["rounds"].append({"round": round_no, "verdict": verdict, "reason": reason, "context_chars": context_chars})
    if verdict == "revise":
        a["practice"] = str(r.get("practice") or a["practice"]).strip()
        a["category"] = _norm_category(r.get("category")) or a["category"]
        a["adoption"] = _norm_adoption(r.get("adoption")) or a["adoption"]
    return verdict


def step_validate(ctx: RunContext) -> None:
    t = ctx.step("validate")
    cfg = ctx.cfg("validate", {})
    p = ctx.project
    cands = getattr(ctx, "extracted", [])
    if not cands:
        ctx.accepted, ctx.rejected = [], []
        ctx.finish(t, "skipped", "nothing to validate")
        return
    system = ctx.workflow.prompt("00_system", taxonomy=innovation_types.prompt_text())
    system = _with_examples(ctx, t, system)   # reviewer-curated good / bad examples (Setup page)
    bs = cfg.get("approaches_per_call", 8)
    expand_on = set(cfg.get("expand_on", ["expand", "unsure"]))
    workers = cfg.get("parallel_calls", 4)

    def judge(chunk, template, with_context):
        blocks = []
        for a in chunk:
            u = a["unit"]
            if with_context:
                wide, s0, e0 = expand(u, ctx.units, cfg.get("expand_chars", 1600))
                marked = wide[: u.start - s0] + ">>> " + wide[u.start - s0: u.end - s0] + " <<<" + wide[u.end - s0:]
                a["context_span"] = (s0, e0)
                blocks.append(_approach_block(a, "TEXT (unit with surrounding context):\n" + marked))
            else:
                blocks.append(_approach_block(a, "UNIT TEXT:\n" + u.numbered_text()))
        prompt = ctx.workflow.prompt(template, **_project_fields(p), approaches="\n\n".join(blocks))
        try:
            return chunk, ctx.llm.complete_json("validate", system, prompt, retries=2, cache_system=True)
        except Exception as e:
            return chunk, {"error": f"{type(e).__name__}: {str(e)[:200]}"}

    def run_round(items, template, with_context, round_no):
        errors, last = 0, ""
        pending = []
        batches = [items[i:i + bs] for i in range(0, len(items), bs)]
        for chunk, data in _pmap(lambda c: judge(c, template, with_context), batches, workers):
            if data.get("error"):
                errors += 1
                last = data["error"]
                continue
            by_id = {str(r.get("approach_id", "")).strip(): r for r in data.get("results", []) if isinstance(r, dict)}
            for a in chunk:
                r = by_id.get(a["approach_id"])
                if r is None:
                    a["rounds"].append({"round": round_no, "verdict": "no_answer", "reason": "", "context_chars": 0})
                    pending.append(a)
                    continue
                ctx_chars = (a["context_span"][1] - a["context_span"][0]) if with_context else a["unit"].chars
                v = _apply_verdict(a, r, round_no, ctx_chars)
                if v in expand_on and not with_context:
                    pending.append(a)
        return pending, errors, last, len(batches)

    pending, errors, last, calls = run_round(cands, "02_validate", False, 1)
    expanded = len(pending)
    for k in range(cfg.get("max_expansions", 1)):
        if not pending:
            break
        pending, e2, l2, c2 = run_round(pending, "03_revalidate", True, k + 2)
        errors, calls = errors + e2, calls + c2
        last = l2 or last
    accepted, rejected = [], []
    for a in cands:
        final = a["rounds"][-1]["verdict"] if a["rounds"] else "no_answer"
        if final in ("accept", "revise"):
            accepted.append(a)
        else:
            rejected.append(a)
    ctx.accepted, ctx.rejected = accepted, rejected
    if errors:
        ctx.record.error = f"validate: {errors} of {calls} calls failed ({last})"
        ctx.finish(t, "failed", ctx.record.error)
        return
    ctx.finish(t, note=f"{len(accepted)} accepted, {len(rejected)} rejected; {expanded} sent to the expanded-context round; {calls} calls",
               accepted=len(accepted), rejected=len(rejected), expanded=expanded, calls=calls)


# ----------------------------------------------------------------------------
def _options(shares):
    return "\n".join(f"- {s.name} ({s.pct:g}%)" if s.pct is not None else f"- {s.name}" for s in shares) or "- (none listed)"


def step_codes(ctx: RunContext) -> None:
    """One sector and one theme per accepted approach, from the project's own lists."""
    t = ctx.step("codes")
    cfg = ctx.cfg("codes", {})
    p = ctx.project
    items = getattr(ctx, "accepted", [])
    if not items:
        ctx.finish(t, "skipped", "no accepted approaches")
        return
    lead_sector = p.sectors[0].name if p.sectors else ""
    lead_theme = p.themes[0].name if p.themes else ""
    if len(p.sectors) <= 1 and len(p.themes) <= 1:
        for a in items:
            a["sector"], a["theme"], a["code_reason"] = lead_sector, lead_theme, "single option in projects.csv"
        ctx.finish(t, note="single sector / theme option: assigned directly")
        return
    bs = cfg.get("batch_size", 30)
    batches = [items[i:i + bs] for i in range(0, len(items), bs)]

    def call(chunk):
        block = "\n".join(f"[{a['approach_id']}] ({a['category']}) {a['practice']} - {a['what_is_done']}" for a in chunk)
        prompt = ctx.workflow.prompt("04_codes", **_project_fields(p), sector_options=_options(p.sectors), theme_options=_options(p.themes), approaches=block)
        try:
            return chunk, ctx.llm.complete_json("codes", "You assign World Bank sector and theme codes. Answer with JSON only.", prompt, retries=2)
        except Exception as e:
            return chunk, {"error": f"{type(e).__name__}: {str(e)[:200]}"}

    errs, n_ok = [], 0
    for chunk, data in _pmap(call, batches, cfg.get("parallel_calls", 4)):
        if data.get("error"):
            errs.append(data["error"])
        by_id = {str(r.get("approach_id", "")).strip(): r for r in data.get("results", []) if isinstance(r, dict)}
        for a in chunk:
            r = by_id.get(a["approach_id"])
            if r:
                a["sector"] = _match_name(r.get("sector", ""), p.sectors) or lead_sector
                a["theme"] = _match_name(r.get("theme", ""), p.themes) or lead_theme
                a["code_reason"] = str(r.get("reason", ""))
                n_ok += 1
            else:
                a["sector"], a["theme"], a["code_reason"] = lead_sector, lead_theme, "fallback: lead sector / theme (no answer)"
    if errs:
        ctx.record.error = f"codes: {len(errs)} of {len(batches)} calls failed ({errs[0]})"
        ctx.finish(t, "failed", ctx.record.error)
        return
    ctx.finish(t, note=f"{n_ok} of {len(items)} approaches coded by the model; {len(batches)} calls")


# ----------------------------------------------------------------------------
def step_merge(ctx: RunContext) -> None:
    """Group accepted approaches that describe the same practice (one call)."""
    t = ctx.step("merge")
    cfg = ctx.cfg("merge", {})
    items = getattr(ctx, "accepted", [])
    ctx.groups = [[a] for a in items]
    if not cfg.get("enabled", True) or len(items) < 2:
        ctx.finish(t, "skipped", "merge disabled or fewer than two approaches")
        return
    p = ctx.project
    block = "\n".join(f"[{a['approach_id']}] ({a['category']}; {a['adoption']}) {a['practice']} - {a['what_is_done']}" for a in items)
    prompt = ctx.workflow.prompt("05_merge", project_id=p.project_id, project_name=p.project_name, approaches=block)
    try:
        data = ctx.llm.complete_json("merge", "You deduplicate extracted practices. Answer with JSON only.", prompt, retries=2)
    except Exception as e:
        ctx.record.error = f"merge: {type(e).__name__}: {str(e)[:200]}"
        ctx.finish(t, "failed", ctx.record.error)
        return
    by_id = {a["approach_id"]: a for a in items}
    seen, groups = set(), []
    for g in data.get("groups", []) or []:
        members = [by_id[m] for m in (str(x).strip() for x in g.get("members", [])) if m in by_id and m not in seen]
        if not members:
            continue
        seen.update(m["approach_id"] for m in members)
        label = str(g.get("practice", "")).strip()
        if label:
            members[0]["practice_merged"] = label
        groups.append(members)
    for a in items:                       # anything the model forgot stays as its own approach
        if a["approach_id"] not in seen:
            groups.append([a])
    ctx.groups = groups
    ctx.finish(t, note=f"{len(items)} approaches -> {len(groups)} after merging duplicates", merged=len(items) - len(groups))


# ----------------------------------------------------------------------------
def _evidence(s, u):
    return Evidence(u.doc.guid, u.doc.doc_type, u.doc.doc_date, u.doc.file_name, s.start, s.end, s.text, "exact", 1.0)


def step_aggregate(ctx: RunContext) -> None:
    """One Approach per merged group; every evidence sentence becomes a row of the evidence table."""
    t = ctx.step("aggregate")
    cfg = ctx.cfg("aggregation", {})
    p = ctx.project
    headline = set(cfg.get("headline_adoption", ["apply"]))
    rows = []
    for n, members in enumerate(getattr(ctx, "groups", []), 1):
        members = sorted(members, key=lambda a: (-ADOPTION_RANK[a["adoption"]], a["unit"].index))
        lead = members[0]
        aid = f"{p.project_id}-A{n}"
        adoption = max((m["adoption"] for m in members), key=lambda a: ADOPTION_RANK[a])
        cat = collections.Counter(m["category"] for m in members).most_common(1)[0][0]
        name = lead.get("practice_merged") or lead["practice"]
        ev_pairs = []
        for m in members:
            for s in m["evidence"]:
                if all(s.start != e.start for e, _ in ev_pairs):
                    ev_pairs.append((s, m))
        ev_pairs = ev_pairs[: cfg.get("max_evidence_kept", 60)]
        evs = [_evidence(s, m["unit"]) for s, m in ev_pairs]
        rounds = max(len(m["rounds"]) for m in members)
        ap = Approach(
            approach_id=aid, project_id=p.project_id, name=name, description=lead["what_is_done"],
            evidence=evs[0], extra_evidence=evs[1:],
            why_innovative=f"category {cat}; adoption {adoption}; judged in {rounds} round(s)" + ("; context expanded" if rounds > 1 else ""),
            status="validated" if adoption in headline else "mentioned_only")
        ap.category = Attribute(cat, cat[:4].upper(), None, lead["reason"], "confirmed")
        ap.category_solution = Attribute("", "", None, "")
        ap.sector = Attribute(lead.get("sector", ""), "", None, lead.get("code_reason", ""), "confirmed")
        ap.theme = Attribute(lead.get("theme", ""), "", None, lead.get("code_reason", ""), "confirmed")
        ap.adoption = Attribute(adoption, "", None, lead["rounds"][-1]["reason"] if lead["rounds"] else lead["reason"], "confirmed")
        ctx.record.approaches.append(ap)
        for k, (s, m) in enumerate(ev_pairs, 1):
            u = m["unit"]
            rows.append({"row_id": f"{aid}-E{k}", "approach_id": aid, "evidence_no": k, "number_of_evidence": len(ev_pairs), "project_id": p.project_id,
                         "doc_id": u.doc.guid, "doc_type": u.doc.doc_type, "doc_date": u.doc.doc_date, "file_name": u.doc.file_name,
                         "unit_id": u.unit_id, "para_no": u.para_no, "sentence_position": s.position, "char_start": s.start, "char_end": s.end,
                         "sentence": s.text, "practice": m["practice"], "category": m["category"], "adoption": m["adoption"],
                         "sector": m.get("sector", ""), "theme": m.get("theme", ""), "extractor_reason": m["reason"],
                         "judge_rounds": len(m["rounds"]), "judge_verdict": m["rounds"][-1]["verdict"] if m["rounds"] else "",
                         "judge_reason": m["rounds"][-1]["reason"] if m["rounds"] else "", "keywords_hit": ";".join(u.cues),
                         "workflow_version": ctx.workflow.version, "run_id": ctx.record.run_id})
    ctx.record.aec_rows = rows
    ctx.record.exclusion_log = [
        {"guid": a["unit"].doc.guid, "doc_type": a["unit"].doc.doc_type, "position": a["evidence"][0].position,
         "char_start": a["evidence"][0].start, "char_end": a["evidence"][0].end, "sentence": a["evidence"][0].text,
         "candidate_codes": [a["category"]], "route": "judge", "practice": a["practice"],
         "reason": f"{a['rounds'][-1]['verdict']}: {a['rounds'][-1]['reason']}" if a["rounds"] else "no verdict",
         "rounds": a["rounds"]}
        for a in getattr(ctx, "rejected", [])]
    live = [a for a in ctx.record.approaches if a.status == "validated"]
    ctx.record.innovative = "Yes" if live else ("Unclear" if ctx.record.approaches else "No")
    ctx.finish(t, note=f"{len(ctx.record.approaches)} approaches ({len(live)} applied), {len(rows)} evidence rows, {len(ctx.record.exclusion_log)} rejected",
               approaches=len(ctx.record.approaches), applied=len(live))
