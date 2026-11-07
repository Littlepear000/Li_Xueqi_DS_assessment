"""Workflow v1 - step implementations.

Entry point: :func:`run`. Each step reads/writes ``ctx.record`` and appends a
:class:`StepTrace`, so the web app can show what happened and why.
"""
from __future__ import annotations

from ...documents import DocumentRef, locate_span, read_text
from ...models import Approach, Attribute, Evidence
from ...taxonomy import dai_pillars, innovation_keywords
from ..base import RunContext

STEP_ORDER = ["screen", "select_documents", "extract", "match", "validate", "replication"]


def run(ctx: RunContext) -> None:
    for name in ctx.cfg("steps", STEP_ORDER):
        globals()[f"step_{name}"](ctx)
        if ctx.record.error:
            break


# ----------------------------------------------------------------------------
# Step 0 - keyword screening
# ----------------------------------------------------------------------------
def step_screen(ctx: RunContext) -> None:
    t = ctx.step("screen")
    docs = ctx.index.for_project(ctx.project.project_id)
    if not docs:
        ctx.record.innovation_tier = "Low"
        ctx.record.innovative = "Unclear"
        ctx.record.error = "no documents"
        ctx.finish(t, "failed", "no documents available for this project")
        return
    sc = ctx.cfg("screening", {})
    distinct: dict[str, dict] = {}
    per_doc = []
    dims = sc.get("dimensions") or None  # None = all seven dimensions of the dictionary
    for d in docs:
        hits = [h for h in innovation_keywords.scan(read_text(d.path)) if not dims or h.dimension in dims]
        per_doc.append({"guid": d.guid, "doc_type": d.doc_type, "distinct_hits": len(hits)})
        for h in hits:
            cur = distinct.get(h.term)
            if cur is None:
                distinct[h.term] = {**h.to_dict(), "guid": d.guid}
            else:
                cur["count"] += h.count
    n = len(distinct)
    tier = innovation_keywords.tier(n, sc.get("high", 4), sc.get("moderate", 2))
    ctx.record.innovation_tier = tier
    ctx.record.innovation_keyword_hits = n
    by_dim: dict[str, int] = {}
    for v in distinct.values():
        by_dim[v["dimension"]] = by_dim.get(v["dimension"], 0) + 1
    ctx.finish(t, note=f"{n} distinct keyword hits -> {tier}",
               distinct_hits=n, tier=tier, by_dimension=by_dim, per_document=per_doc,
               hits=sorted(distinct.values(), key=lambda h: -h["count"])[:60])


# ----------------------------------------------------------------------------
# Step 1 - document selection
# ----------------------------------------------------------------------------
def step_select_documents(ctx: RunContext) -> None:
    t = ctx.step("select_documents")
    rules = ctx.cfg("documents", {})
    docs = ctx.index.for_project(ctx.project.project_id)
    chosen: list[DocumentRef] = []
    for dtype in rules.get("primary", ["PAD", "ProjectPaper", "PID"]):
        cands = [d for d in docs if d.doc_type == dtype]
        if cands:
            # newest of the primary type (e.g. latest Project Paper)
            chosen.append(sorted(cands, key=lambda d: d.doc_date)[-1])
            break
    for dtype in rules.get("supporting", ["ISR"]):
        cands = sorted([d for d in docs if d.doc_type == dtype], key=lambda d: d.doc_date)
        if cands:
            chosen.extend(cands[-1:] if dtype in rules.get("latest_only", []) else cands)
    if not chosen and docs:
        chosen = [docs[0]]
    ctx.docs = chosen
    ctx.record.documents_used = [{**d.to_dict(), "role": "primary" if i == 0 else "supporting"} for i, d in enumerate(chosen)]
    ctx.finish(t, note=", ".join(f"{d.doc_type} {d.doc_date}" for d in chosen) or "none", selected=ctx.record.documents_used)


def _documents_block(ctx: RunContext, max_primary: int, max_supporting: int) -> str:
    parts = []
    for i, d in enumerate(ctx.docs):
        text = read_text(d.path)
        cap = max_primary if i == 0 else max_supporting
        if len(text) > cap:
            text = _focus_window(text, cap)
        parts.append(f"--- document guid={d.guid} type={d.doc_type} date={d.doc_date} file={d.file_name} ---\n{text}")
    return "\n\n".join(parts)


def _focus_window(text: str, cap: int) -> str:
    """When a document is too long, keep the beginning plus windows around keyword hits."""
    head = int(cap * 0.6)
    pieces = [text[:head]]
    budget = cap - head
    hits = innovation_keywords.scan(text)
    hits.sort(key=lambda h: h.first_offset)
    window = 1500
    last_end = head
    for h in hits:
        if budget <= 0:
            break
        s = max(last_end, h.first_offset - window // 2)
        if s < last_end + 200:
            continue
        e = min(len(text), s + window)
        pieces.append("\n[...]\n" + text[s:e])
        budget -= (e - s)
        last_end = e
    return "".join(pieces)


# ----------------------------------------------------------------------------
# Step 2 - extraction
# ----------------------------------------------------------------------------
def step_extract(ctx: RunContext) -> None:
    t = ctx.step("extract")
    sc = ctx.cfg("screening", {})
    if ctx.record.innovation_tier not in sc.get("extract_tiers", ["High", "Moderate"]) and not sc.get("force_extract"):
        ctx.record.innovative = "No"
        ctx.finish(t, "skipped", f"tier {ctx.record.innovation_tier}: below extraction threshold")
        return
    rules = ctx.cfg("documents", {})
    ex = ctx.cfg("extraction", {})
    p = ctx.project
    screen = next((s for s in ctx.record.trace if s.step == "screen"), None)
    kw = ", ".join(f"{h['term']}: {h['count']}" for h in (screen.output.get("hits", [])[:25] if screen else []))
    prompt = ctx.workflow.prompt(
        "01_extract",
        project_id=p.project_id, project_name=p.project_name, country=p.country, vertical=p.vertical,
        lead_practice=p.lead_practice, approval_date=p.approval_date,
        sectors="; ".join(f"{s.name} ({s.pct:g}%)" if s.pct is not None else s.name for s in p.sectors),
        themes="; ".join(f"{s.name} ({s.pct:g}%)" if s.pct is not None else s.name for s in p.themes),
        keyword_hits=kw or "none", max_approaches=ex.get("max_approaches", 5),
        documents=_documents_block(ctx, rules.get("max_chars_primary", 120_000), rules.get("max_chars_supporting", 20_000)),
    )
    data = ctx.llm.complete_json("extract", ctx.workflow.prompts["00_system"], prompt)
    ctx.record.innovative = data.get("innovative", "Unclear")
    dropped = []
    docs_by_guid = {d.guid: d for d in ctx.docs}
    for i, item in enumerate(data.get("approaches", [])[: ex.get("max_approaches", 5)], 1):
        guid = str(item.get("document_guid", "")).strip()
        doc = docs_by_guid.get(guid) or (ctx.docs[0] if ctx.docs else None)
        sentence = item.get("evidence_sentence", "")
        span = locate_span(doc, sentence, ex.get("min_evidence_similarity", 0.85)) if doc else None
        if span is None:
            # try the other selected documents before giving up
            for d in ctx.docs:
                span = locate_span(d, sentence, ex.get("min_evidence_similarity", 0.85))
                if span:
                    doc = d
                    break
        if span is None:
            dropped.append({"approach_name": item.get("approach_name"), "evidence_sentence": sentence, "reason": "evidence not found in document"})
            continue
        ev = Evidence(doc.guid, doc.doc_type, doc.doc_date, doc.file_name, span.start, span.end, span.text, span.match_kind, span.similarity)
        ctx.record.approaches.append(Approach(
            approach_id=f"{p.project_id}-A{len(ctx.record.approaches) + 1}", project_id=p.project_id,
            name=str(item.get("approach_name", "")).strip(), description=str(item.get("description", "")).strip(),
            evidence=ev, why_innovative=str(item.get("why_innovative", "")).strip()))
    if not ctx.record.approaches and ctx.record.innovative == "Yes":
        ctx.record.innovative = "Unclear"
    ctx.finish(t, note=f"{len(ctx.record.approaches)} approaches kept, {len(dropped)} dropped",
               innovative=ctx.record.innovative, dropped=dropped, raw=data)


# ----------------------------------------------------------------------------
# Step 3 - attribute matching
# ----------------------------------------------------------------------------
def _options(shares) -> str:
    return "\n".join(f"- {s.name} ({s.pct:g}%)" if s.pct is not None else f"- {s.name}" for s in shares) or "- (none listed)"


def _match_name(value: str, shares) -> str:
    """Snap a model answer to one of the project's own codes (exact, then case/space-insensitive, then prefix)."""
    v = (value or "").strip()
    names = [s.name for s in shares]
    if v in names:
        return v
    norm = lambda s: " ".join(s.lower().replace("–", "-").split())
    for n in names:
        if norm(n) == norm(v):
            return n
    for n in names:
        if norm(v) and (norm(v) in norm(n) or norm(n) in norm(v)):
            return n
    return v  # keep the model's answer; validation can still revise it


def step_match(ctx: RunContext) -> None:
    t = ctx.step("match")
    if not ctx.record.approaches:
        ctx.finish(t, "skipped", "no approaches")
        return
    p = ctx.project
    for a in ctx.record.approaches:
        doc = ctx.index.by_guid(a.evidence.guid)
        text = read_text(doc.path) if doc else ""
        s, e = max(0, a.evidence.char_start - 700), min(len(text), a.evidence.char_end + 700)
        data = ctx.llm.complete_json("match", ctx.workflow.prompts["00_system"], ctx.workflow.prompt(
            "02_match", project_id=p.project_id, project_name=p.project_name, country=p.country, vertical=p.vertical,
            lead_practice=p.lead_practice, approach_name=a.name, description=a.description,
            doc_type=a.evidence.doc_type, doc_date=a.evidence.doc_date, evidence=a.evidence.text,
            why_innovative=a.why_innovative, context=text[s:e], taxonomy=dai_pillars.taxonomy_text(),
            sector_options=_options(p.sectors), theme_options=_options(p.themes)))
        cat = data.get("category", {}) or {}
        code = str(cat.get("code", "")).upper().strip()
        pillar = dai_pillars.PILLAR_BY_ID.get(code)
        a.category = Attribute(pillar.name if pillar else code, code, cat.get("confidence"), cat.get("rationale", ""))
        sol = data.get("category_solution", {}) or {}
        scode = str(sol.get("code", "")).upper().strip()
        solution = dai_pillars.SOLUTION_BY_ID.get(scode)
        a.category_solution = Attribute(solution.title if solution else ("none" if scode in ("", "NONE") else scode),
                                        scode if solution else "", sol.get("confidence"), sol.get("rationale", ""))
        sec = data.get("sector", {}) or {}
        a.sector = Attribute(_match_name(sec.get("value", ""), p.sectors), "", sec.get("confidence"), sec.get("rationale", ""))
        th = data.get("theme", {}) or {}
        a.theme = Attribute(_match_name(th.get("value", ""), p.themes), "", th.get("confidence"), th.get("rationale", ""))
    ctx.finish(t, note=f"{len(ctx.record.approaches)} approaches classified")


# ----------------------------------------------------------------------------
# Step 4 - validation against the document
# ----------------------------------------------------------------------------
def step_validate(ctx: RunContext) -> None:
    t = ctx.step("validate")
    if not ctx.cfg("validation", {}).get("enabled", True) or not ctx.record.approaches:
        ctx.finish(t, "skipped", "nothing to validate")
        return
    p = ctx.project
    block = []
    for a in ctx.record.approaches:
        block.append(
            f"[{a.approach_id}] {a.name}\n  description: {a.description}\n  evidence ({a.evidence.doc_type} {a.evidence.doc_date}): \"{a.evidence.text}\"\n"
            f"  category: {a.category.code} {a.category.value}\n  category_solution: {a.category_solution.code or a.category_solution.value} {a.category_solution.value if a.category_solution.code else ''}\n"
            f"  sector: {a.sector.value}\n  theme: {a.theme.value}")
    block.append("Project sector options: " + "; ".join(s.name for s in p.sectors))
    block.append("Project theme options: " + "; ".join(s.name for s in p.themes))
    cap = ctx.cfg("validation", {}).get("max_chars", 60_000)
    data = ctx.llm.complete_json("validate", ctx.workflow.prompts["00_system"], ctx.workflow.prompt(
        "03_validate", project_id=p.project_id, project_name=p.project_name, country=p.country, vertical=p.vertical,
        lead_practice=p.lead_practice, approaches_block="\n\n".join(block), taxonomy=dai_pillars.taxonomy_text(),
        documents=_documents_block(ctx, cap, int(cap * 0.25))))
    verdicts = {v.get("approach_id"): v for v in data.get("approaches", []) if isinstance(v, dict)}
    revised, rejected = 0, 0
    for a in ctx.record.approaches:
        v = verdicts.get(a.approach_id)
        if not v:
            for attr in (a.category, a.category_solution, a.sector, a.theme):
                attr.validated = "confirmed"
            a.status = "validated"
            continue
        if (v.get("approach") or {}).get("verdict") == "rejected":
            a.status = "rejected"
            rejected += 1
            for attr in (a.category, a.category_solution, a.sector, a.theme):
                attr.validated = "rejected"
                attr.validation_note = (v.get("approach") or {}).get("note", "")
            continue
        a.status = "validated"
        for key, attr in (("category", a.category), ("category_solution", a.category_solution), ("sector", a.sector), ("theme", a.theme)):
            vv = v.get(key) or {}
            verdict = vv.get("verdict", "confirmed")
            attr.validated = verdict
            attr.validation_note = vv.get("note", "")
            if verdict == "revised" and vv.get("value"):
                revised += 1
                new = str(vv["value"]).strip()
                if key == "category":
                    pil = dai_pillars.PILLAR_BY_ID.get(new.upper())
                    attr.code, attr.value = (new.upper(), pil.name) if pil else (attr.code, new)
                elif key == "category_solution":
                    sol = dai_pillars.SOLUTION_BY_ID.get(new.upper())
                    attr.code, attr.value = (new.upper(), sol.title) if sol else ("", new)
                elif key == "sector":
                    attr.value = _match_name(new, p.sectors)
                else:
                    attr.value = _match_name(new, p.themes)
    if data.get("innovative") in ("Yes", "No", "Unclear"):
        ctx.record.innovative = data["innovative"]
    ctx.finish(t, note=f"{revised} attributes revised, {rejected} approaches rejected", reasoning=data.get("reasoning", ""), raw=data)


# ----------------------------------------------------------------------------
# Step 5 - replication (portfolio level, incremental)
# ----------------------------------------------------------------------------
def step_replication(ctx: RunContext) -> None:
    t = ctx.step("replication")
    rc = ctx.cfg("replication", {})
    p = ctx.project
    store = ctx.portfolio
    live = [a for a in ctx.record.approaches if a.status != "rejected"]
    explicit = []
    if rc.get("explicit_reference", True):
        full = "\n".join(read_text(d.path) for d in ctx.index.for_project(p.project_id))
        explicit = store.explicit_references(p.project_id, full)
    n_sim = 0
    import contextlib
    with (ctx.lock if ctx.lock is not None else contextlib.nullcontext()):
        for a in live:
            text = f"{a.name}. {a.description} {a.evidence.text}"
            links = list(explicit)
            if rc.get("similarity", True):
                sim = store.similar_approaches(a.approach_id, p.project_id, text, rc.get("similarity_threshold", 0.45), rc.get("max_links", 5))
                n_sim += len(sim)
                links.extend(sim)
            a.replication = links
            store.upsert(a.approach_id, p.project_id, p.approval_date, a.name, text)
        store.save()
    ctx.finish(t, note=f"{len(explicit)} explicit references, {n_sim} similar approaches",
               explicit=[l.to_dict() for l in explicit], store_size=len(store.approaches))
