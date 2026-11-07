"""Workflow v6 - v5 plus an innovation test, the project-level innovation screen and Data Sheet exclusion.

Pipeline (see config.yaml ``steps``)::

    screen -> locate_pad -> units -> candidates -> extract -> validate -> codes -> merge -> aggregate -> replication

Changes from v5 (see CHANGELOG.md):

* ``screen`` (as in v1): distinct hits of the 7-dimension innovation dictionary across the project's
  documents -> ``innovation_tier`` High / Moderate / Low on every record; ``screening.gate`` (default
  false) limits extraction to High / Moderate projects.
* ``candidates``: units of the PAD Data Sheet (conditions, legal covenants, ESCP tables) are marked
  ``legal_condition`` and not sent to extraction; every unit also gets ``innovation_cues`` (hits of the
  non-technology dimensions), shown to the model next to the ``digital_cues`` - a signal, not a gate.
* prompts: an approach must pass three tests (specificity, digital, INNOVATION); the extractor gives
  ``innovation_basis``; the judge returns a fixed ``reject_code``.
* ``merge``: Data Sheet sentences that refer to an approach found in the body are attached as extra evidence.
* v6.3-v6.5: ``novelty`` - one call per project (v6.5): digital & AI core? and before 2019 rare_or_absent (kept) /
  in_use / common (dropped).
* v6.1: ``codes`` assigns a sector only (no theme); ``merge`` groups by (sector, category) - one approach per
  sector x category - and one call names the multi-member groups.

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
import re
from concurrent.futures import ThreadPoolExecutor

from ...models import Approach, Attribute, Evidence
from ...documents import read_text
from ...segment import segment
from ...taxonomy import ddat, innovation_keywords, innovation_types
from ...units import build_units, expand
from ..base import RunContext
from ...examples import with_examples as _with_examples
from ..v1.steps import _match_name, step_screen as _v1_screen
from ..v2.steps import step_replication  # noqa: F401  (portfolio-level, unchanged)

CATEGORIES = list(innovation_types.CATEGORIES)
ADOPTION_RANK = {"apply": 3, "prospect": 2, "discuss": 1}
REJECT_CODES = ["generic", "not_digital", "not_innovative", "legal_or_compliance_condition",
                "background_or_other_programme", "unsupported_by_evidence"]
TECH_DIMENSION = "enabling_technologies"

# PAD Data Sheet / legal boilerplate (conditions, covenants, ESCP tables).
# Case-sensitive unless (?i): Data Sheet headers are capitalised, and 'conditions' in body text must not match.
LEGAL_PATTERNS = [
    r"(?i)Type\s+Financing\s+source\s+Description",
    r"(?i)Sections?\s+and\s+Description",
    r"(?:^|\s)Conditions(?=\s*$|\s+Type\b)",
    r"Legal\s+Covenants",
    r"(?i)No\s+withdrawal\s+shall\s+be\s+made",
    r"Effectiveness\s+(?:IBRD|IDA)\b",
    r"Disbursement\s+(?:IBRD|IDA)\b",
]


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


def _norm_reject_code(v) -> str:
    v = re.sub(r"[^a-z_]+", "_", str(v or "").strip().lower()).strip("_")
    return v if v in REJECT_CODES else ("other" if v else "")


# ----------------------------------------------------------------------------
def step_scope(ctx: RunContext) -> None:
    """v6.9: approval date >= scope.min_approval_date (calendar) and status not in scope.exclude_status.
    An out-of-scope project gets ``error = 'out of scope: ...'`` and the run stops before any document is read."""
    from ...scope import OUT_OF_SCOPE, scope_reason
    t = ctx.step("scope")
    reason = scope_reason(ctx.cfg("scope", {}), ctx.project)
    if reason:
        ctx.record.error = f"{OUT_OF_SCOPE}: {reason}"
        ctx.record.innovative = ""
        ctx.finish(t, note=f"out of scope - {reason}; not read, no model calls")
        return
    ctx.finish(t, note=f"in scope (approved {ctx.project.approval_date or 'n/a'}, status {ctx.project.status or 'n/a'})")


def step_screen(ctx: RunContext) -> None:
    """Project-level innovation screen (v1 step 0): distinct dictionary hits -> innovation_tier.

    With ``screening.gate: true`` a Low-tier project is not extracted (``ctx.screen_gated``)."""
    _v1_screen(ctx)
    sc = ctx.cfg("screening", {})
    ctx.screen_gated = bool(sc.get("gate", False)) and ctx.record.innovation_tier not in sc.get("extract_tiers", ["High", "Moderate"])
    if ctx.screen_gated and ctx.record.trace:
        ctx.record.trace[-1].note += " - gate on: not extracted"


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


def mark_legal_conditions(units, cfg: dict) -> int:
    """Flag PAD Data Sheet / legal-condition units (``u.legal_condition``).

    A unit is flagged when it matches a Data Sheet pattern. In addition, the Data Sheet zone at the front of
    the document is flagged as a whole: from the first matching unit that lies in the first
    ``datasheet_zone_share`` of the document up to the first numbered paragraph or the STRATEGIC CONTEXT heading."""
    pats = [re.compile(p) for p in cfg.get("legal_patterns", LEGAL_PATTERNS)]
    body_start = re.compile(cfg.get("body_start_pattern", r"\b(?:I\.\s*)?STRATEGIC\s+CONTEXT\b"))
    for u in units:
        u.legal_condition = any(p.search(u.text) for p in pats)
    if units and cfg.get("datasheet_zone", True):
        limit = max(1, int(len(units) * cfg.get("datasheet_zone_share", 0.25)))
        first = next((k for k, u in enumerate(units[:limit]) if u.legal_condition), None)
        if first is not None:
            for u in units[first:]:
                if u.para_no is not None or body_start.search(u.text):
                    break
                u.legal_condition = True
    return sum(1 for u in units if u.legal_condition)


def step_candidates(ctx: RunContext) -> None:
    """Units that carry a digital / data / AI cue; Data Sheet units excluded; innovation cues recorded."""
    t = ctx.step("candidates")
    cfg = ctx.cfg("candidates", {})
    tech = [p for p in innovation_keywords.PATTERNS if p.dimension == TECH_DIMENSION]
    innov = [p for p in innovation_keywords.PATTERNS if p.dimension != TECH_DIMENSION]
    n_legal = mark_legal_conditions(ctx.units, ctx.cfg("legal_conditions", {}))
    for u in ctx.units:
        u.innovation_cues = sorted({p.term for p in innov if p.regex.search(u.text)})
    if getattr(ctx, "screen_gated", False):
        ctx.candidates = []
        ctx.finish(t, "skipped", f"screen gate: innovation tier {ctx.record.innovation_tier} is not extracted", candidate_units=0, legal_condition=n_legal)
        return
    kept, n_innov = [], 0
    for u in ctx.units:
        if cfg.get("drop_boilerplate", True) and u.boilerplate:
            continue
        if cfg.get("drop_legal_conditions", True) and u.legal_condition:
            continue
        text = u.text
        hits = ddat.keyword_hits(text)
        terms = sorted({w for ws in hits.values() for w in ws})
        terms += [p.term for p in tech if p.regex.search(text) and p.term not in terms]
        u.cues = terms
        if terms or not cfg.get("require_cue", True):
            kept.append(u)
            n_innov += bool(u.innovation_cues)
    cap = cfg.get("max_units_per_project", 150)
    dropped = 0
    if len(kept) > cap:
        kept.sort(key=lambda u: -len(u.cues) / max(1, u.chars))
        dropped = len(kept) - cap
        kept = sorted(kept[:cap], key=lambda u: u.index)
    ctx.candidates = kept
    ctx.finish(t, note=f"{len(kept)} of {len(ctx.units)} units carry a digital / AI cue ({n_innov} also an innovation cue); "
                       f"{n_legal} Data Sheet / legal-condition units excluded" + (f"; {dropped} dropped over the cap" if dropped else ""),
               candidate_units=len(kept), dropped=dropped, legal_condition=n_legal, with_innovation_cue=n_innov)


# ----------------------------------------------------------------------------
def _unit_header(u) -> str:
    return (f"{u.unit_id} (doc={u.doc.doc_type} {u.doc.doc_date}; para {u.para_no if u.para_no else '-'}; "
            f"digital_cues={', '.join(u.cues[:6]) or '-'}; innovation_cues={', '.join(getattr(u, 'innovation_cues', [])[:6]) or '-'})")


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
        block = "\n\n".join(f"--- {_unit_header(u)}\n{u.numbered_text()}" for u in chunk)
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
                    "innovation_basis": str(a.get("innovation_basis", "")).strip(),
                    "category_reason": str(a.get("category_reason", "")).strip(),
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
    u = a["unit"]
    return (f"--- {a['approach_id']}\npractice: {a['practice']}\nwhat_is_done: {a['what_is_done']}\ncategory: {a['category']}; adoption: {a['adoption']}\n"
            f"innovation_basis: {a.get('innovation_basis') or '-'}\n"
            f"unit {u.unit_id}: digital_cues={', '.join(u.cues[:6]) or '-'}; innovation_cues={', '.join(getattr(u, 'innovation_cues', [])[:6]) or '-'}\n"
            f"evidence sentences: {ev}\nextractor's reason: {a['reason']}\n{text}")


def _apply_verdict(a, r, round_no, context_chars):
    verdict = str(r.get("verdict", "")).strip().lower()
    reason = str(r.get("reason", "")).strip()
    code = _norm_reject_code(r.get("reject_code")) if verdict == "reject" else ""
    a["rounds"].append({"round": round_no, "verdict": verdict, "reason": reason, "reject_code": code, "context_chars": context_chars})
    if verdict in ("accept", "revise") and str(r.get("innovation_basis") or "").strip():
        a["innovation_basis"] = str(r["innovation_basis"]).strip()
    if verdict == "revise" and "Category:" in reason and _norm_category(r.get("category")) not in ("", a["category"]):
        a["category_reason"] = f"{_norm_category(r.get('category'))}: " + reason.split("Category:", 1)[1].strip()
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
                    a["rounds"].append({"round": round_no, "verdict": "no_answer", "reason": "", "reject_code": "", "context_chars": 0})
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
    codes = collections.Counter((a["rounds"][-1].get("reject_code") or "uncoded") if a["rounds"] else "no_answer" for a in rejected)
    ctx.finish(t, note=f"{len(accepted)} accepted, {len(rejected)} rejected" + (f" ({', '.join(f'{k} {v}' for k, v in codes.most_common())})" if rejected else "")
                       + f"; {expanded} sent to the expanded-context round; {calls} calls",
               accepted=len(accepted), rejected=len(rejected), expanded=expanded, calls=calls, reject_codes=dict(codes))


# ----------------------------------------------------------------------------
def _options(shares):
    return "\n".join(f"- {s.name} ({s.pct:g}%)" if s.pct is not None else f"- {s.name}" for s in shares) or "- (none listed)"


def step_codes(ctx: RunContext) -> None:
    """One sector per accepted approach, from the project's own projects.csv list (v6.1: no theme)."""
    t = ctx.step("codes")
    cfg = ctx.cfg("codes", {})
    p = ctx.project
    items = getattr(ctx, "accepted", [])
    if not items:
        ctx.finish(t, "skipped", "no accepted approaches")
        return
    lead_sector = p.sectors[0].name if p.sectors else ""
    if len(p.sectors) <= 1:
        for a in items:
            a["sector"], a["code_reason"] = lead_sector, "single sector in projects.csv"
        ctx.finish(t, note="single sector option: assigned directly")
        return
    bs = cfg.get("batch_size", 30)
    batches = [items[i:i + bs] for i in range(0, len(items), bs)]

    def call(chunk):
        block = "\n".join(f"[{a['approach_id']}] ({a['category']}) {a['practice']} - {a['what_is_done']}" for a in chunk)
        prompt = ctx.workflow.prompt("04_codes", **_project_fields(p), sector_options=_options(p.sectors), approaches=block)
        try:
            return chunk, ctx.llm.complete_json("codes", "You assign World Bank sector codes. Answer with JSON only.", prompt, retries=2)
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
                a["code_reason"] = str(r.get("reason", ""))
                n_ok += 1
            else:
                a["sector"], a["code_reason"] = lead_sector, "fallback: lead sector (no answer)"
    if errs:
        ctx.record.error = f"codes: {len(errs)} of {len(batches)} calls failed ({errs[0]})"
        ctx.finish(t, "failed", ctx.record.error)
        return
    ctx.finish(t, note=f"{n_ok} of {len(items)} approaches given a sector by the model; {len(batches)} calls")


# ----------------------------------------------------------------------------
def step_merge(ctx: RunContext) -> None:
    """Group accepted approaches by (sector, category): one approach per sector x category (v6.1).

    The grouping itself is deterministic; one model call only names each group that has several
    members (a practice wording covering them and a one-sentence description)."""
    t = ctx.step("merge")
    cfg = ctx.cfg("merge", {})
    items = getattr(ctx, "accepted", [])
    keys = cfg.get("group_by", ["sector", "category"])
    buckets: dict[tuple, list] = {}
    for a in sorted(items, key=lambda a: (-ADOPTION_RANK[a["adoption"]], a["unit"].index)):
        buckets.setdefault(tuple(a.get(k, "") for k in keys), []).append(a)
    groups = list(buckets.values())
    ctx.groups = groups
    multi = [g for g in groups if len(g) > 1]
    if not cfg.get("enabled", True) or not multi:
        n_legal = _attach_legal_evidence(ctx, cfg)
        ctx.finish(t, "skipped" if not items else "ok", f"{len(items)} approaches -> {len(groups)} by {' x '.join(keys)}; no group needed naming"
                   + (f"; {n_legal} Data Sheet sentences attached" if n_legal else ""), merged=len(items) - len(groups), legal_evidence=n_legal)
        return
    p = ctx.project
    block = "\n\n".join(f"--- G{k} ({' / '.join(str(x) for x in key)})\n" + "\n".join(f"[{a['approach_id']}] ({a['adoption']}) {a['practice']} - {a['what_is_done']}" for a in g)
                         for k, (key, g) in enumerate(buckets.items(), 1) if len(g) > 1)
    prompt = ctx.workflow.prompt("05_merge", project_id=p.project_id, project_name=p.project_name, groups=block)
    try:
        data = ctx.llm.complete_json("merge", "You consolidate extracted practices into approaches. Answer with JSON only.", prompt, retries=2)
    except Exception as e:
        ctx.record.error = f"merge: {type(e).__name__}: {str(e)[:200]}"
        ctx.finish(t, "failed", ctx.record.error)
        return
    names = {str(g.get("group_id", "")).strip(): g for g in data.get("groups", []) or [] if isinstance(g, dict)}
    for k, (key, g) in enumerate(buckets.items(), 1):
        r = names.get(f"G{k}")
        if len(g) > 1 and r:
            if str(r.get("practice", "")).strip():
                g[0]["practice_merged"] = str(r["practice"]).strip()
            if str(r.get("description", "")).strip():
                g[0]["description_merged"] = str(r["description"]).strip()
    n_legal = _attach_legal_evidence(ctx, cfg)
    ctx.finish(t, note=f"{len(items)} approaches -> {len(groups)} by {' x '.join(keys)}" + (f"; {n_legal} Data Sheet sentences attached as extra evidence" if n_legal else ""),
               merged=len(items) - len(groups), legal_evidence=n_legal)


_STOP = set("""the and for with from that this which into their its are was were will been being under over such than then also
using used use based system systems project projects program programme data digital platform service services""".split())


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower()) if w not in _STOP}


def _attach_legal_evidence(ctx: RunContext, cfg: dict) -> int:
    """Data Sheet / legal-condition sentences that refer to an approach found in the body become extra evidence
    of that approach (never a new approach). A sentence is attached to the group whose practice wording shares
    at least ``legal_min_shared`` content words and ``legal_min_overlap`` of the practice's words with it."""
    if not cfg.get("attach_legal_evidence", True):
        return 0
    legal_units = [u for u in ctx.units if getattr(u, "legal_condition", False)]
    groups = getattr(ctx, "groups", [])
    if not legal_units or not groups:
        return 0
    keys = []
    for g in groups:
        words = set()
        for m in g:
            words |= _content_tokens(f"{m.get('practice_merged', '')} {m['practice']}")
        keys.append(words)
    n = 0
    min_shared, min_overlap = cfg.get("legal_min_shared", 2), cfg.get("legal_min_overlap", 0.4)
    for u in legal_units:
        for snt in u.sentences:
            toks = _content_tokens(snt.text)
            best, best_k = 0.0, None
            for k, words in enumerate(keys):
                shared = len(words & toks)
                if words and shared >= min_shared and shared / len(words) >= min_overlap and shared / len(words) > best:
                    best, best_k = shared / len(words), k
            if best_k is not None:
                groups[best_k][0].setdefault("legal_evidence", []).append((snt, u))
                n += 1
    return n


# ----------------------------------------------------------------------------
def _evidence(s, u):
    return Evidence(u.doc.guid, u.doc.doc_type, u.doc.doc_date, u.doc.file_name, s.start, s.end, s.text, "exact", 1.0)


def step_novelty(ctx: RunContext) -> None:
    """v6.3/v6.4: ask the model up to ``novelty.rounds`` times (default 3) (1) whether digital / data / AI is the CORE of
    each final approach (``digital_pass``, default core) and (2) whether its KIND was not common before ``novelty.year`` (2019).
    Failing (1) in any round drops it with reject_code ``not_digital``. An approach is dropped as not innovative as soon as ONE answer says it was common
    before, or already existed before (``novelty.fail_on``). Rounds are independent calls (own client at
    ``novelty.temperature``); later rounds only ask about approaches that are still in. Dropped approaches go to the
    exclusion log with reject_code ``existed_before_<year>``."""
    import dataclasses
    from ...llm import LLMClient
    t = ctx.step("novelty")
    cfg = ctx.cfg("novelty", {}) or {}
    groups = getattr(ctx, "groups", [])
    if not cfg.get("enabled", True) or not groups:
        ctx.finish(t, "skipped", "novelty check disabled" if groups else "no approaches")
        return
    p = ctx.project
    year, rounds = int(cfg.get("year", 2019)), int(cfg.get("rounds", 3))
    statement = str(cfg.get("statement", "Before {year}, this kind of approach was rare or absent in development projects.")).format(year=year)
    fail_on = set(cfg.get("fail_on", ["in_use", "common"]))
    digital_pass = set(cfg.get("digital_pass", ["core"]))   # v6.4: the digital & AI answer must be one of these
    max_chars = int(cfg.get("max_chars_per_approach", 1500))
    settings = dataclasses.replace(ctx.llm.settings, temperature=float(cfg.get("temperature", ctx.llm.settings.temperature)))
    client = LLMClient(settings, cancel=ctx.llm.cancel)
    ids = {f"G{k}": g for k, g in enumerate(groups, 1)}
    for g in groups:
        g[0]["novelty"] = []

    def source(g) -> str:
        lead = g[0]
        txt = lead["unit"].text
        extra = [sn.text for m in g[1:] for sn in m["evidence"]][:3]
        out = txt + ("\n(also: " + " | ".join(extra) + ")" if extra else "")
        return out[:max_chars]

    alive, errors, calls = dict(ids), [], 0
    for r in range(1, rounds + 1):
        if not alive:
            break
        block = "\n\n".join(f"--- {gid}\npractice: {g[0].get('practice_merged') or g[0]['practice']}\ncategory: {g[0]['category']}; sector: {g[0].get('sector', '')}\n"
                              f"source text: {source(g)}" for gid, g in alive.items())
        prompt = ctx.workflow.prompt("06_novelty", **_project_fields(p), round=r, rounds=rounds, statement=statement, year=year, approaches=block)
        calls += 1
        try:
            data = client.complete_json("novelty", "You judge whether development-project approaches were new at a given date. Answer with JSON only.", prompt, retries=2)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {str(e)[:200]}")
            continue
        by_id = {str(x.get("approach_id", "")).strip(): x for x in data.get("results", []) if isinstance(x, dict)}
        for gid in list(alive):
            x = by_id.get(gid)
            v = str((x or {}).get("verdict", "")).strip().lower() or "no_answer"
            dg = str((x or {}).get("digital", "")).strip().lower() or "no_answer"
            alive[gid][0]["novelty"].append({"round": r, "verdict": v, "digital": dg, "reason": str((x or {}).get("reason", "")).strip()})
            if v in fail_on or (x is not None and dg not in digital_pass):
                del alive[gid]
    ctx.llm.calls.extend(client.calls)   # usage and call counts of this step
    if errors:
        ctx.record.error = f"novelty: {len(errors)} of {calls} calls failed ({errors[0]})"
        ctx.finish(t, "failed", ctx.record.error)
        return
    kept, dropped, n_digital = [], 0, 0
    for gid, g in ids.items():
        if gid in alive:
            kept.append(g)
            continue
        dropped += 1
        last = g[0]["novelty"][-1]
        not_digital = last.get("digital") not in digital_pass
        n_digital += not_digital
        code = "not_digital" if not_digital else f"existed_before_{year}"
        why = f"digital: {last['digital']}" if not_digital else last["verdict"]
        for m in g:
            m["rounds"].append({"round": len(m["rounds"]) + 1, "verdict": "reject", "reject_code": code,
                                "reason": f"final check round {last['round']}: {why} - {last['reason']}", "context_chars": 0})
            ctx.rejected.append(m)
    ctx.groups = kept
    ctx.finish(t, note=f"{len(ids)} approaches checked in {calls} call(s): {len(kept)} kept (digital & AI core, rare or absent before {year}); "
                       f"{n_digital} dropped as not digital, {dropped - n_digital} as existing before {year}",
               checked=len(ids), kept=len(kept), dropped=dropped, dropped_not_digital=n_digital, calls=calls)


def step_aggregate(ctx: RunContext) -> None:
    """One Approach per merged group; every evidence sentence becomes a row of the evidence table."""
    t = ctx.step("aggregate")
    cfg = ctx.cfg("aggregation", {})
    p = ctx.project
    headline = set(cfg.get("headline_adoption", ["apply"]))
    rows = []
    for n, members in enumerate(getattr(ctx, "groups", []), 1):
        lead = members[0]   # groups are already ordered: highest adoption first, then document order
        aid = f"{p.project_id}-A{n}"
        adoption = max((m["adoption"] for m in members), key=lambda a: ADOPTION_RANK[a])
        cat = collections.Counter(m["category"] for m in members).most_common(1)[0][0]
        name = lead.get("practice_merged") or lead["practice"]
        practices = list(dict.fromkeys(m["practice"] for m in members))
        description = lead.get("description_merged") or lead["what_is_done"]
        if len(practices) > 1:
            description += " Practices: " + "; ".join(practices) + "."
        ev_pairs = []
        for m in members:
            for s in m["evidence"]:
                if all(s.start != e.start for e, _ in ev_pairs):
                    ev_pairs.append((s, m))
        legal = [(snt, u) for m in members for snt, u in m.get("legal_evidence", [])]
        ev_pairs = ev_pairs[: cfg.get("max_evidence_kept", 60)]
        evs = [_evidence(s, m["unit"]) for s, m in ev_pairs]
        for snt, u in legal:
            if all(snt.start != e.char_start for e in evs):
                e = _evidence(snt, u)
                e.match_kind = "legal_condition"
                evs.append(e)
        cues = sorted({c for m in members for c in getattr(m["unit"], "innovation_cues", [])})
        basis = next((m.get("innovation_basis") for m in members if m.get("innovation_basis")), "")
        rounds = max(len(m["rounds"]) for m in members)
        ap = Approach(
            approach_id=aid, project_id=p.project_id, name=name, description=description,
            evidence=evs[0], extra_evidence=evs[1:],
            why_innovative=(basis + " | " if basis else "") + f"category {cat}; adoption {adoption}; judged in {rounds} round(s)" + ("; context expanded" if rounds > 1 else "")
                           + (f"; final check: digital core, {lead['novelty'][-1]['verdict']} before {ctx.cfg('novelty', {}).get('year', 2019)}" if lead.get("novelty") else ""),
            status="validated" if adoption in headline else "mentioned_only", innovation_basis=basis, innovation_cues=cues)
        ap.category = Attribute(cat, cat[:4].upper(), None, lead.get("category_reason") or lead["reason"], "confirmed")
        ap.category_solution = Attribute("", "", None, "")
        ap.sector = Attribute(lead.get("sector", ""), "", None, lead.get("code_reason", ""), "confirmed")
        ap.theme = None   # v6.1: approaches carry a sector only
        ap.adoption = Attribute(adoption, "", None, lead["rounds"][-1]["reason"] if lead["rounds"] else lead["reason"], "confirmed")
        ctx.record.approaches.append(ap)
        for k, (s, m) in enumerate(ev_pairs, 1):
            u = m["unit"]
            rows.append({"row_id": f"{aid}-E{k}", "approach_id": aid, "evidence_no": k, "number_of_evidence": len(ev_pairs), "project_id": p.project_id,
                         "doc_id": u.doc.guid, "doc_type": u.doc.doc_type, "doc_date": u.doc.doc_date, "file_name": u.doc.file_name,
                         "unit_id": u.unit_id, "para_no": u.para_no, "sentence_position": s.position, "char_start": s.start, "char_end": s.end,
                         "sentence": s.text, "practice": m["practice"], "category": m["category"], "adoption": m["adoption"],
                         "sector": m.get("sector", ""), "extractor_reason": m["reason"],
                         "judge_rounds": len(m["rounds"]), "judge_verdict": m["rounds"][-1]["verdict"] if m["rounds"] else "",
                         "judge_reason": m["rounds"][-1]["reason"] if m["rounds"] else "", "keywords_hit": ";".join(u.cues),
                         "innovation_cues": ";".join(getattr(u, "innovation_cues", [])), "innovation_basis": m.get("innovation_basis", ""),
                         "evidence_source": "body", "workflow_version": ctx.workflow.version, "run_id": ctx.record.run_id})
        k0 = len(ev_pairs)
        for j, (snt, u) in enumerate(legal, 1):
            rows.append({"row_id": f"{aid}-L{j}", "approach_id": aid, "evidence_no": k0 + j, "number_of_evidence": len(ev_pairs), "project_id": p.project_id,
                         "doc_id": u.doc.guid, "doc_type": u.doc.doc_type, "doc_date": u.doc.doc_date, "file_name": u.doc.file_name,
                         "unit_id": u.unit_id, "para_no": u.para_no, "sentence_position": snt.position, "char_start": snt.start, "char_end": snt.end,
                         "sentence": snt.text, "practice": lead["practice"], "category": cat, "adoption": adoption,
                         "sector": lead.get("sector", ""), "extractor_reason": "", "judge_rounds": 0, "judge_verdict": "",
                         "judge_reason": "Data Sheet / legal-condition sentence attached to an approach found in the body", "keywords_hit": "",
                         "innovation_cues": "", "innovation_basis": "", "evidence_source": "legal_condition",
                         "workflow_version": ctx.workflow.version, "run_id": ctx.record.run_id})
    ctx.record.aec_rows = rows
    ctx.record.exclusion_log = [
        {"guid": a["unit"].doc.guid, "doc_type": a["unit"].doc.doc_type, "position": a["evidence"][0].position,
         "char_start": a["evidence"][0].start, "char_end": a["evidence"][0].end, "sentence": a["evidence"][0].text,
         "candidate_codes": [a["category"]], "route": "judge", "practice": a["practice"],
         "reason": f"{a['rounds'][-1]['verdict']}: {a['rounds'][-1]['reason']}" if a["rounds"] else "no verdict",
         "reject_code": (a["rounds"][-1].get("reject_code") or "") if a["rounds"] else "",
         "innovation_basis": a.get("innovation_basis", ""), "innovation_cues": ";".join(getattr(a["unit"], "innovation_cues", [])),
         "rounds": a["rounds"]}
        for a in getattr(ctx, "rejected", [])]
    live = [a for a in ctx.record.approaches if a.status == "validated"]
    ctx.record.innovative = "Yes" if live else ("Unclear" if ctx.record.approaches else "No")
    ctx.finish(t, note=f"{len(ctx.record.approaches)} approaches ({len(live)} applied), {len(rows)} evidence rows, {len(ctx.record.exclusion_log)} rejected",
               approaches=len(ctx.record.approaches), applied=len(live))
