"""Workflow v3 - v2 sentence coding plus an applied / mentioned check per approach."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ...context import build_context
from ...models import Attribute
from ..base import RunContext
from ..v2.steps import (LEVEL_RANK, step_aggregate, step_candidates, step_classify, step_map_solutions,  # noqa: F401
                        step_replication, step_screen, step_segment, step_select_documents)

MENTION_REASONS = {"future_plan", "aspiration_or_vision", "other_program", "lesson_or_reference", "option_considered", "parent_or_prior", "unclear"}


def run(ctx: RunContext) -> None:
    for name in ctx.cfg("steps"):
        globals()[f"step_{name}"](ctx)
        if ctx.record.error:
            break


def _render_context(ctx_data: dict, start: int, end: int) -> str:
    """Flatten the formatted window into prompt text with the evidence sentence marked."""
    out = []
    for b in ctx_data["blocks"]:
        t = b["text"]
        if b["char_start"] <= start < b["char_end"]:
            a, z = start - b["char_start"], min(len(t), end - b["char_start"])
            t = t[:a] + ">>> " + t[a:z] + " <<<" + t[z:]
        prefix = {"heading": "\n## ", "subpoint": "   ", "bullet": "   - ", "para": "\n"}.get(b["kind"], "\n")
        out.append(prefix + t)
    return "\n".join(out).strip()


def step_adoption(ctx: RunContext) -> None:
    t = ctx.step("adoption")
    cfg = ctx.cfg("adoption", {})
    p = ctx.project
    if not ctx.record.approaches:
        ctx.finish(t, "skipped", "no approaches")
        return
    rows_by_code: dict[str, list[dict]] = {}
    for r in ctx.record.aec_rows:
        rows_by_code.setdefault(r["approach_code"], []).append(r)
    levels_ok = set(cfg.get("check_levels", ["L1", "L2", "L3"]))

    def check(ap):
        code = ap.approach_id.split("-")[-1]
        rows = rows_by_code.get(code, [])
        top = max((r["evidence_level"] for r in rows), key=lambda x: LEVEL_RANK[x], default="L2")
        if top not in levels_ok:
            return ap, None
        doc = ctx.index.by_guid(ap.evidence.guid)
        if doc is None:
            return ap, None
        cdata = build_context(doc, ap.evidence.char_start, ap.evidence.char_end, cfg.get("context_pages", 1), rows, code)
        levels = {lvl: sum(1 for r in rows if r["evidence_level"] == lvl) for lvl in ("L1", "L2", "L3")}
        prompt = ctx.workflow.prompt("03_adoption", project_id=p.project_id, project_name=p.project_name, country=p.country,
                                     lead_practice=p.lead_practice, approval_date=p.approval_date, status=p.status,
                                     approach_code=code, approach_name=ap.name.split(" ", 1)[1] if " " in ap.name else ap.name,
                                     n_rows=len(rows), levels=f"L1 {levels['L1']}, L2 {levels['L2']}, L3 {levels['L3']}",
                                     doc_type=ap.evidence.doc_type, doc_date=ap.evidence.doc_date,
                                     context=_render_context(cdata, ap.evidence.char_start, ap.evidence.char_end))
        try:
            data = ctx.llm.complete_json("adoption", "You review World Bank project documents and apply the stated decision rules literally. Answer with JSON only.", prompt, retries=2)
        except Exception as e:
            return ap, {"adoption": "mentioned", "mention_for": "unclear", "confidence": 0.0, "reason": f"model error: {type(e).__name__}", "evidence_level": top}
        return ap, data

    n_applied = n_mentioned = 0
    with ThreadPoolExecutor(max_workers=max(1, cfg.get("parallel", 6))) as ex:
        for ap, data in ex.map(check, ctx.record.approaches):
            code = ap.approach_id.split("-")[-1]
            top = max((r["evidence_level"] for r in rows_by_code.get(code, [])), key=lambda x: LEVEL_RANK[x], default="L2")
            if data is None:
                ap.adoption = Attribute("mentioned", "unclear", None, "not checked (evidence level outside check_levels)", "")
                ap.status = "referenced_only" if top == "L1" else ap.status
                n_mentioned += 1
                continue
            adoption = str(data.get("adoption", "mentioned")).lower().strip()
            reason_cat = str(data.get("mention_for", "")).lower().strip()
            conf = data.get("confidence")
            try:
                conf = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf = None
            if adoption == "applied" and conf is not None and conf < cfg.get("min_confidence_applied", 0.5):
                adoption, reason_cat = "mentioned", reason_cat or "unclear"
            if adoption != "applied":
                adoption = "mentioned"
                reason_cat = reason_cat if reason_cat in MENTION_REASONS else "unclear"
            else:
                reason_cat = ""
            restated = str(data.get("evidence_level", top)).upper().strip()
            restated = restated if restated in LEVEL_RANK else top
            ap.adoption = Attribute(adoption, reason_cat, conf, str(data.get("reason", "")).strip(), "confirmed")
            ap.why_innovative = f"evidence level {top} (re-read: {restated}); adoption {adoption}" + (f" ({reason_cat})" if reason_cat else "")
            if adoption == "applied" and restated in ctx.cfg("aggregation", {}).get("headline_levels", ["L2", "L3"]):
                ap.status = "validated"
                n_applied += 1
            elif adoption == "applied":
                ap.status = "referenced_only"  # applied but only L1-type evidence after re-reading
                n_mentioned += 1
            else:
                ap.status = "mentioned_only"
                n_mentioned += 1
    live = [a for a in ctx.record.approaches if a.status == "validated"]
    ctx.record.innovative = "Yes" if live else ("Unclear" if ctx.record.approaches else "No")
    ctx.finish(t, note=f"{n_applied} applied (L2/L3), {n_mentioned} mentioned / not applied", applied=n_applied, mentioned=n_mentioned)
