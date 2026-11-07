"""Replication and scaling pipeline (Methodology Note 3).

Steps (numbering follows the Note):

1. **Find cues** - every non-boilerplate sentence of every project document is
   scanned for replication cues, scaling cues, other P-codes and known project
   names / acronyms (:mod:`piaa.linkage.cues`).
2. **Attach the cue to an approach** - a cue is a candidate for an approach when
   it sits within one sentence of an *anchor* of that approach. Anchors are the
   approach's stored evidence sentence plus the sentences of the same project
   whose TF-IDF similarity to the approach (name + description) is at least
   ``anchor_threshold`` - a stand-in for the other corpus rows of Note 1 until
   the corpus keeps all evidence rows. The model then confirms which approach,
   if any, the cue is about. Unattached cues are logged as project-level cues.
3. **Resolve the source** - P-code, then project name / acronym (alias index).
4. **Classify** - same family -> scaling; different family -> replication
   (named / unnamed); scaling cue without a source in an ISR / project paper ->
   expansion in project.
5. **Structural scaling** - earlier and later family members carrying the
   same approach code get a ``structural`` scaling link.
6. **Verify replication** - a resolved source in the portfolio that carries the
   same approach code earlier -> ``verified``; otherwise flagged.

Steps 2-4 use the model and run twice (run A / run B); links present in only
one run, or classified differently, are flagged for review.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..catalog import load_projects
from ..config import LLMSettings
from ..documents import build_index
from ..llm import LLMClient
from ..segment import segment
from ..taxonomy import ddat
from . import cues as C
from .families import Edge, from_metadata

WORKFLOW_VERSION = "linkage-v1"
PROMPTS = Path(__file__).parent / "prompts"
EXPANSION_DOC_TYPES = {"ISR", "ProjectPaper", "ICR"}
FAMILY_DOC_TYPES = {"PAD", "PID", "ProjectPaper", "ProgramDocument"}
STRENGTH_RANK = {"verified": 3, "named": 2, "unnamed": 1}
FORM_RANK = {"additional_financing": 4, "series": 3, "expansion_in_project": 2, "structural": 1}


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------
def load_corpus(db_path: Path) -> pd.DataFrame:
    """Validated approaches from the latest review DB (rejected ones dropped)."""
    with sqlite3.connect(db_path) as c:
        A = pd.read_sql("SELECT approach_id, project_id, n, name, description, evidence_json, category_solution_code AS solution_code, status "
                        "FROM approaches WHERE status != 'rejected'", c)
    ev = A["evidence_json"].fillna("{}").map(json.loads)
    A["ev_guid"] = ev.map(lambda e: e.get("guid", ""))
    A["ev_start"] = ev.map(lambda e: e.get("char_start", -1))
    A["ev_text"] = ev.map(lambda e: e.get("text", ""))
    A["ev_doc_type"] = ev.map(lambda e: e.get("doc_type", ""))
    A["ev_doc_date"] = ev.map(lambda e: e.get("doc_date", ""))
    return A.drop(columns=["evidence_json"])


def _sentences(index, pids):
    out = {}
    for pid in pids:
        out[pid] = {d.guid: segment(d) for d in index.for_project(pid)}
    return out


# ----------------------------------------------------------------------------
# Steps 1-2 (rule part): cue scan and candidate attachment
# ----------------------------------------------------------------------------
def candidate_cues(pid, docs, approaches, aliases, anchor_threshold=0.15, max_cues=45, family_window=140):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    flat = [(g, i, s) for g, ss in docs.items() for i, s in enumerate(ss) if not s.boilerplate]
    if not flat:
        return [], [], []
    texts = [s.text for _, _, s in flat]
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit(texts)
    sim = cosine_similarity(vec.transform([f"{a.name}. {a.description}" for a in approaches.itertuples()]), vec.transform(texts)) \
        if len(approaches) else None
    anchors: dict[tuple, dict[str, str]] = defaultdict(dict)       # (guid, pos) -> {approach_id: method}
    for j, a in enumerate(approaches.itertuples()):
        for k, (g, i, s) in enumerate(flat):
            if g == a.ev_guid and s.start <= a.ev_start < s.end + 1:
                anchors[(g, i)][a.approach_id] = "evidence_window"
            elif sim is not None and sim[j, k] >= anchor_threshold:
                anchors[(g, i)].setdefault(a.approach_id, "semantic_window")
    attached, project_level, fam = [], [], []
    for g, i, s in flat:
        ss = docs[g]
        before = ss[i - 1].text if i > 0 else ""
        after = ss[i + 1].text if i + 1 < len(ss) else ""
        ctx_cue = bool(C.REPLICATION_RE.search(before + " " + after) or C.SCALING_RE.search(before + " " + after))
        hit = C.scan(s.text, pid, aliases, need_names=ctx_cue)
        # family candidates: another P-code close to family language
        if s.doc.doc_type in FAMILY_DOC_TYPES:
            for code in hit.pcodes:
                for m in C.PCODE_RE.finditer(s.text):
                    if m.group(0) != code:
                        continue
                    win = s.text[max(0, m.start() - family_window): m.end() + family_window]
                    if C.FAMILY_RE.search(win):
                        fam.append({"pcode": code, "guid": g, "doc_type": s.doc.doc_type, "doc_date": s.doc.doc_date,
                                    "text": s.text, "distance": 0})
                        break
        if not hit.any or not (hit.replication or hit.scaling or hit.pcodes or hit.names):
            continue
        near: dict[str, str] = {}
        for d in (0, -1, 1):
            for aid, meth in anchors.get((g, i + d), {}).items():
                if aid not in near or meth == "evidence_window":
                    near[aid] = meth
        row = {"guid": g, "position": i, "doc_type": s.doc.doc_type, "doc_date": s.doc.doc_date, "cue_sentence": s.text,
               "before": before, "after": after, "cue_families": "+".join(hit.families()),
               "cue_terms": "; ".join(hit.replication + hit.scaling), "pcodes": ";".join(hit.pcodes), "named_pids": ";".join(hit.names)}
        # a P-code / name alone is a cue only when replication / scaling language is in the sentence or its context
        if not (hit.replication or hit.scaling):
            ctx_hit = C.scan(before + " " + after, pid)
            if not (ctx_hit.replication or ctx_hit.scaling):
                continue
        if near:
            row["candidates"] = near
            attached.append(row)
        else:
            project_level.append(row)
    # keep the most promising cues if a project has very many (evidence-window first, then replication language)
    attached.sort(key=lambda r: (-any(m == "evidence_window" for m in r["candidates"].values()),
                                 -("replication" in r["cue_families"]), -len(r["candidates"])))
    for r in attached[max_cues:]:
        r["dropped"] = "over_cap"
    project_level += [r for r in attached[max_cues:]]
    attached = attached[:max_cues]
    for n, r in enumerate(attached, 1):
        r["cue_id"] = f"{pid}-C{n:02d}"
    # one family candidate per P-code (first occurrence)
    seen, fam_u = set(), []
    for f in fam:
        if f["pcode"] not in seen:
            seen.add(f["pcode"])
            fam_u.append(f)
    return attached, project_level, fam_u[:25]


# ----------------------------------------------------------------------------
# Steps 2-4 (model part)
# ----------------------------------------------------------------------------
def _ddat_codes_text() -> str:
    return "\n".join(f"{a.code} {a.name}" for a in ddat.approaches().values())


def _cut(s: str, n: int = 600) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + " ..."


def build_prompt(p, approaches, cues, fam) -> str:
    tpl = (PROMPTS / "01_link.md").read_text(encoding="utf-8")
    ap = "\n".join(f"- {a.approach_id} | {a.name} | {_cut(a.description, 300)} | \"{_cut(a.ev_text, 300)}\"" for a in approaches.itertuples())
    cu = "\n\n".join(
        f"[{c['cue_id']}] ({c['doc_type']} {c['doc_date']}) candidate approaches: {', '.join(sorted(c['candidates']))}\n"
        f"  before: {_cut(c['before'])}\n  CUE: {_cut(c['cue_sentence'], 900)}\n  after: {_cut(c['after'])}" for c in cues) or "(none)"
    fa = "\n\n".join(f"[{f['pcode']}] ({f['doc_type']} {f['doc_date']}) {_cut(f['text'], 700)}" for f in fam) or "(none)"
    return (tpl.replace("{{project_id}}", p.project_id).replace("{{project_name}}", p.project_name)
            .replace("{{country}}", p.country).replace("{{approval_date}}", p.approval_date)
            .replace("{{ddat_codes}}", _ddat_codes_text()).replace("{{approaches}}", ap)
            .replace("{{cues}}", cu).replace("{{family_candidates}}", fa))


def _mock_judgement(approaches, cues, fam) -> dict:
    """Rule-only stand-in for the model (provider='mock'): attach to all candidates, type from cue family."""
    codes = list(ddat.approaches())
    out = {"approach_codes": [{"approach_id": a.approach_id, "code": codes[hash(a.name) % len(codes)]} for a in approaches.itertuples()],
           "cues": [], "family": []}
    for c in cues:
        t = "replication" if "replication" in c["cue_families"] else "scaling"
        src = (c["pcodes"] or c["named_pids"]).split(";")[0] if (c["pcodes"] or c["named_pids"]) else ""
        out["cues"].append({"cue_id": c["cue_id"], "approach_ids": sorted(c["candidates"]), "link_type": t,
                            "source_relation": "other_family" if src else "unspecified", "source_text": src,
                            "source_named": bool(src), "form_hint": None, "reason": "mock"})
    for f in fam:
        out["family"].append({"pcode": f["pcode"], "relation": "unrelated", "reason": "mock"})
    return out


def judge_project(pid, p, approaches, cues, fam, settings: LLMSettings, cache_dir: Path, run_tag: str) -> dict:
    prompt = build_prompt(p, approaches, cues, fam)
    system = (PROMPTS / "00_system.md").read_text(encoding="utf-8")
    key = hashlib.sha1(f"{settings.provider}|{settings.model}|{run_tag}|{system}|{prompt}".encode()).hexdigest()[:16]
    cpath = cache_dir / f"{pid}.{run_tag}.{key}.json"
    if cpath.exists():
        return json.loads(cpath.read_text(encoding="utf-8"))
    t0 = time.time()
    if settings.provider == "mock":
        data = _mock_judgement(approaches, cues, fam)
    else:
        client = LLMClient(settings)
        data = client.complete_json("linkage", system, prompt, retries=1, cache_system=True)
    data = data if isinstance(data, dict) else {}
    data["_meta"] = {"run": run_tag, "seconds": round(time.time() - t0, 1), "prompt_chars": len(prompt), "model": settings.model}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


# ----------------------------------------------------------------------------
# Steps 3-4: resolve + classify
# ----------------------------------------------------------------------------
def classify_cue(pid, cue, j, families, aliases, projects):
    """One model judgement for one cue -> list of link dicts (one per approach)."""
    lt = (j.get("link_type") or "none").lower()
    if lt not in ("replication", "scaling"):
        return [], "model_none"
    aids = [a for a in (j.get("approach_ids") or []) if a in cue["candidates"]]
    if not aids:
        return [], "project_level"
    rel = (j.get("source_relation") or "unspecified").lower()
    src_text = (j.get("source_text") or "").strip()
    src_pid, how = aliases.resolve(src_text, pid) if src_text else ("", "")
    if not src_pid and rel in ("this_project",):
        src_pid, how = pid, "self"
    # an AF / restructuring with its own P-code: "this project" scaling points to the parent
    parent = families.af_parent(pid)
    if parent and src_pid == pid:
        src_pid, how = parent, "af_parent"
    hint = (j.get("form_hint") or "") or ""
    link_type, form = None, None
    if src_pid:
        if families.same_family(pid, src_pid):
            link_type = "scaling"
            kind = families.edge_kind(pid, src_pid)
            if kind == "self":
                if cue["doc_type"] in EXPANSION_DOC_TYPES:
                    form = "additional_financing" if hint == "additional_financing" or "additional financing" in cue["cue_terms"] else "expansion_in_project"
                else:
                    return [], "planned_expansion"
            else:
                form = kind if kind in ("additional_financing", "series") else "series"
                if how == "af_parent":
                    form = "additional_financing"
        else:
            link_type, form = "replication", "named"
    else:
        if rel == "same_family":
            link_type, form = "scaling", (hint if hint in ("additional_financing", "series") else "series")
        elif rel == "other_family" or lt == "replication":
            link_type, form = "replication", ("named" if j.get("source_named") and src_text else "unnamed")
        else:  # scaling without a source
            if cue["doc_type"] in EXPANSION_DOC_TYPES:
                link_type, form = "scaling", ("additional_financing" if hint == "additional_financing" else "expansion_in_project")
                src_pid, how = pid, "self"
                if parent:
                    src_pid, how, form = parent, "af_parent", "additional_financing"
            else:
                return [], "planned_expansion"
    out = []
    for aid in aids:
        out.append({"target_row_id": aid, "attach_method": cue["candidates"][aid], "link_type": link_type, "form_or_strength": form,
                    "cue_id": cue["cue_id"], "cue_sentence": cue["cue_sentence"], "cue_context_before": cue["before"],
                    "cue_context_after": cue["after"], "cue_doc_id": cue["guid"], "cue_doc_type": cue["doc_type"],
                    "cue_doc_date": cue["doc_date"], "cue_terms": cue["cue_terms"], "source_text": src_text,
                    "source_project_id": src_pid, "source_resolution": how, "source_relation_model": rel,
                    "reason": j.get("reason", "")})
    return out, "linked"


def _source_key(l):
    return l["source_project_id"] or ("text:" + C._norm(l["source_text"])[:60] if l["source_text"] else "unnamed")


def dedupe(links):
    """One link per target approach x source; keep the strongest form."""
    best = {}
    for l in links:
        k = (l["target_row_id"], _source_key(l), l["link_type"])
        r = STRENGTH_RANK.get(l["form_or_strength"], 0) + FORM_RANK.get(l["form_or_strength"], 0)
        if k not in best or r > best[k][0]:
            best[k] = (r, l)
    return [v[1] for v in best.values()]


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def build_links(db_path, raw_dir, out_root, label="run", provider="anthropic", model="claude-sonnet-4-5",
                runs=2, workers=8, anchor_threshold=0.15, max_cues=45, project_ids=None, log=print) -> Path:
    db_path, raw_dir, out_root = Path(db_path), Path(raw_dir), Path(out_root)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = out_root / f"{stamp}_{label}"
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = out_root / "_llm_cache"
    projects = load_projects(raw_dir / "projects.csv")
    A = load_corpus(db_path)
    if project_ids:
        A = A[A.project_id.isin(project_ids)]
    pids = sorted(A.project_id.unique())
    index = build_index([raw_dir / "documents"] + ([raw_dir / "api_supplement" / "documents"] if (raw_dir / "api_supplement" / "documents").exists() else []))
    log(f"[1] segmenting documents of {len(projects)} projects ...")
    sents = _sentences(index, sorted(set(projects) | set(pids)))
    aliases = C.AliasIndex.build(projects, {p: [s for ss in d.values() for s in ss] for p, d in sents.items()})
    log(f"    alias index: {len(aliases.resolved())} unambiguous aliases")

    # steps 1-2 rule part
    per = {}
    for pid in pids:
        at, pl, fam = candidate_cues(pid, sents.get(pid, {}), A[A.project_id == pid], aliases, anchor_threshold, max_cues)
        per[pid] = (at, pl, fam)
    log(f"[2] cues attached: {sum(len(v[0]) for v in per.values())}, project-level: {sum(len(v[1]) for v in per.values())}, "
        f"family candidates: {sum(len(v[2]) for v in per.values())}")

    # model part, run A / run B
    settings = LLMSettings(provider=provider, model=model, max_tokens=8000)
    judg: dict[str, dict[str, dict]] = {}
    jobs = [(pid, r) for r in ["run-A", "run-B"][:runs] for pid in pids if per[pid][0] or per[pid][2] or len(A[A.project_id == pid])]
    log(f"[3] model calls: {len(jobs)} ({provider}/{model})")
    errors = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(judge_project, pid, projects[pid], A[A.project_id == pid], per[pid][0], per[pid][2],
                          settings, cache_dir, r): (pid, r) for pid, r in jobs if pid in projects}
        for n, f in enumerate(cf.as_completed(futs), 1):
            pid, r = futs[f]
            try:
                judg.setdefault(r, {})[pid] = f.result()
            except Exception as e:  # keep going; logged
                errors.append({"project_id": pid, "run": r, "error": repr(e)[:300]})
            if n % 25 == 0:
                log(f"    {n}/{len(jobs)} done")
    runA = judg.get("run-A", {})

    # approach codes (run A; run B disagreement flagged)
    code_rows = []
    for pid in pids:
        ca = {x.get("approach_id"): str(x.get("code", "")) for x in runA.get(pid, {}).get("approach_codes", []) if isinstance(x, dict)}
        cb = {x.get("approach_id"): str(x.get("code", "")) for x in judg.get("run-B", {}).get(pid, {}).get("approach_codes", []) if isinstance(x, dict)}
        for a in A[A.project_id == pid].itertuples():
            code = ca.get(a.approach_id, "")
            code_rows.append({"approach_id": a.approach_id, "project_id": pid, "approach_label": a.name, "solution_code": a.solution_code,
                              "approach_code": code, "approach_name": ddat.approaches()[code].name if code in ddat.approaches() else ("None" if code == "NONE" else ""),
                              "code_run_b": cb.get(a.approach_id, ""), "code_agreed": (code == cb.get(a.approach_id, code))})
    codes = pd.DataFrame(code_rows)
    code_of = dict(zip(codes.approach_id, codes.approach_code))

    # families: metadata + model-confirmed document edges (run A)
    fam = from_metadata(projects)
    fam_rows = []
    for pid in pids:
        cand = {f["pcode"]: f for f in per[pid][2]}
        for x in runA.get(pid, {}).get("family", []) or []:
            if not isinstance(x, dict) or x.get("pcode") not in cand:
                continue
            relation, f = x.get("relation", "unrelated"), cand[x["pcode"]]
            kind = {"this_is_af_of": "additional_financing", "af_of_this": "additional_financing",
                    "earlier_phase": "series", "later_phase": "series"}.get(relation)
            fam_rows.append({"project_id": pid, "other_project_id": x["pcode"], "relation": relation, "edge_kind": kind or "",
                             "other_in_portfolio": x["pcode"] in projects, "doc_type": f["doc_type"], "doc_date": f["doc_date"],
                             "sentence": f["text"], "reason": x.get("reason", "")})
            if kind:
                a, b = (pid, x["pcode"]) if relation != "af_of_this" else (x["pcode"], pid)
                fam.add(Edge(a, b, kind, "document", f"{'this_is_af_of' if kind == 'additional_financing' else relation}: " + f["text"][:300], f["guid"]))

    # steps 3-4 for each run
    def links_from(run):
        links, logged = [], []
        for pid in pids:
            at, pl, _ = per[pid]
            js = {x.get("cue_id"): x for x in (judg.get(run, {}).get(pid, {}).get("cues", []) or []) if isinstance(x, dict)}
            for c in at:
                j = js.get(c["cue_id"])
                if j is None:
                    logged.append({**_log_row(pid, c), "outcome": "no_model_answer"})
                    continue
                ls, outcome = classify_cue(pid, c, j, fam, aliases, projects)
                for l in ls:
                    l["target_project_id"] = pid
                links += ls
                if outcome != "linked":
                    logged.append({**_log_row(pid, c), "outcome": outcome, "model_link_type": j.get("link_type"),
                                   "model_approach_ids": ";".join(j.get("approach_ids") or []), "reason": j.get("reason", "")})
            if run == "run-A":
                logged += [{**_log_row(pid, c), "outcome": c.get("dropped", "no_approach_nearby")} for c in pl]
        return dedupe(links), logged

    links_a, cue_log = links_from("run-A")
    links_b, _ = links_from("run-B") if runs > 1 else ([], [])

    # step 5: structural scaling
    by_pid_code = defaultdict(set)
    for aid, pid in zip(A.approach_id, A.project_id):
        if code_of.get(aid) and code_of[aid] != "NONE":
            by_pid_code[(pid, code_of[aid])].add(aid)
    existing = {(l["target_row_id"], l["source_project_id"]) for l in links_a}
    structural = []
    for fid, members in fam.members().items():
        mem = [m for m in members if m in set(pids)]
        for i, later in enumerate(mem):
            for earlier in mem[:i]:
                for (pp, code), aids in list(by_pid_code.items()):
                    if pp != later or not by_pid_code.get((earlier, code)):
                        continue
                    for aid in aids:
                        if (aid, earlier) in existing:
                            continue
                        structural.append({"target_row_id": aid, "target_project_id": later, "attach_method": "structural",
                                           "link_type": "scaling", "form_or_strength": "structural", "cue_id": "", "cue_sentence": "",
                                           "cue_context_before": "", "cue_context_after": "", "cue_doc_id": "", "cue_doc_type": "",
                                           "cue_doc_date": "", "cue_terms": "", "source_text": projects[earlier].project_name,
                                           "source_project_id": earlier, "source_resolution": "family", "source_relation_model": "",
                                           "reason": f"Family {fid}: {earlier} and {later} both carry approach {code}"})

    # step 6: verify + enrich
    ev_date = dict(zip(A.approach_id, A.ev_doc_date))

    def enrich(l):
        src, tgt = l["source_project_id"], l["target_project_id"]
        code = code_of.get(l["target_row_id"], "")
        l["approach_code"] = code
        l["approach_name"] = ddat.approaches()[code].name if code in ddat.approaches() else ""
        l["in_scope"] = code in ddat.approaches()   # False when the model coded the approach NONE (no digital element)
        l["source_in_portfolio"] = bool(src) and src in projects
        l["family_id"] = fam.family_id(tgt)
        l["source_family_id"] = fam.family_id(src) if src else ""
        same = "unknown"
        if src in projects and tgt in projects:
            same = projects[src].country == projects[tgt].country
        l["same_country"] = same
        has = "unknown"
        if l["source_in_portfolio"] and src != tgt:
            src_aids = by_pid_code.get((src, code), set())
            ref_date = l["cue_doc_date"] or projects[tgt].approval_date
            has = any((ev_date.get(x) or "9999") <= ref_date for x in src_aids) or (
                bool(src_aids) and (projects[src].approval_date or "9999") < (projects[tgt].approval_date or ""))
        elif src == tgt and src:
            has = True
        l["source_has_approach"] = has
        l["verification"] = "not_applicable"
        if l["link_type"] == "replication" and l["source_in_portfolio"]:
            l["verification"] = "passed" if has is True else "failed"
            if has is True:
                l["form_or_strength"] = "verified"
        return l

    links_a = [enrich(l) for l in links_a] + [enrich(l) for l in structural]
    links_b = [enrich(l) for l in links_b] + [dict(l) for l in structural]

    # QC: run A vs run B
    def qkey(l):
        return (l["target_row_id"], _source_key(l), l["link_type"])
    kb = {qkey(l): l["form_or_strength"] for l in links_b}
    ka = {qkey(l) for l in links_a}
    for l in links_a:
        k = qkey(l)
        if l["form_or_strength"] == "structural":
            l["qc"] = "rule_based"
        elif runs < 2:
            l["qc"] = "single_run"
        elif k not in kb:
            l["qc"] = "run_A_only"
        elif kb[k] != l["form_or_strength"] and not (l["form_or_strength"] == "verified" and kb[k] in ("named", "verified")):
            l["qc"] = "form_differs"
        else:
            l["qc"] = "agreed"
        l["review_status"] = "flagged" if (l["qc"] in ("run_A_only", "form_differs") or l["verification"] == "failed") else (
            "agreed" if l["qc"] in ("agreed", "rule_based") else "pending")
    b_only = [{**l, "qc": "run_B_only", "review_status": "flagged"} for l in links_b if qkey(l) not in ka]

    cols = ["link_id", "target_row_id", "target_project_id", "approach_code", "approach_name", "link_type", "form_or_strength",
            "cue_sentence", "cue_context_before", "cue_context_after", "cue_doc_id", "cue_doc_type", "cue_doc_date",
            "source_text", "source_project_id", "source_in_portfolio", "source_has_approach", "family_id", "source_family_id",
            "same_country", "reason", "verification", "attach_method", "source_resolution", "source_relation_model",
            "cue_terms", "cue_id", "in_scope", "qc", "workflow_version", "run_id", "review_status", "reviewer_note"]
    L = pd.DataFrame(links_a)
    if len(L):
        L = L.sort_values(["target_project_id", "target_row_id", "link_type"]).reset_index(drop=True)
        L["link_id"] = [f"L-{i:06d}" for i in range(1, len(L) + 1)]
        L["workflow_version"], L["run_id"], L["reviewer_note"] = WORKFLOW_VERSION, "run-A", ""
    L = L.reindex(columns=cols)
    L.to_csv(out / "approach_link_table.csv", index=False)
    pd.DataFrame(b_only).reindex(columns=cols).to_csv(out / "qc_run_b_only_links.csv", index=False)
    codes.to_csv(out / "approach_codes.csv", index=False)
    pd.DataFrame(cue_log).to_csv(out / "cue_log.csv", index=False)
    pd.DataFrame(fam_rows).to_csv(out / "family_candidates.csv", index=False)
    pd.DataFrame([e.to_dict() for e in fam.edges]).to_csv(out / "family_edges.csv", index=False)
    fm = [{"family_id": k, "members": ";".join(v), "n_members": len(v), "n_in_portfolio": sum(m in projects for m in v)}
          for k, v in fam.members().items() if len(v) > 1]
    pd.DataFrame(fm).to_csv(out / "families.csv", index=False)
    if errors:
        pd.DataFrame(errors).to_csv(out / "errors.csv", index=False)

    # parallel adoption (context only)
    linked_pairs = {frozenset((l["target_project_id"], l["source_project_id"])) for l in links_a if l["source_project_id"]}
    par = []
    for code in sorted({c for c in codes.approach_code if c and c != "NONE"}):
        ps = sorted({p for (p, c) in by_pid_code if c == code})
        pairs = [(a, b) for i, a in enumerate(ps) for b in ps[i + 1:] if not fam.same_family(a, b)]
        par.append({"approach_code": code, "approach_name": ddat.approaches()[code].name, "n_projects": len(ps),
                    "n_families": len({fam.family_id(p) for p in ps}), "cross_family_pairs": len(pairs),
                    "pairs_with_link": sum(frozenset(p) in linked_pairs for p in pairs),
                    "parallel_adoption_pairs": sum(frozenset(p) not in linked_pairs for p in pairs)})
    pd.DataFrame(par).to_csv(out / "parallel_adoption.csv", index=False)

    from ..versioning import package_version
    manifest = {"workflow_version": WORKFLOW_VERSION, "package_version": package_version(), "built_at": stamp, "db": str(db_path), "provider": provider, "model": model,
                "runs": runs, "anchor_threshold": anchor_threshold, "max_cues": max_cues, "n_projects": len(pids),
                "n_approaches": int(len(A)), "n_links": int(len(L)), "model_errors": len(errors)}
    (out / "linkage_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    log(f"[done] {len(L)} links -> {out}")
    return out


def _log_row(pid, c):
    return {"project_id": pid, "cue_id": c.get("cue_id", ""), "doc_type": c["doc_type"], "doc_date": c["doc_date"],
            "cue_families": c["cue_families"], "cue_terms": c["cue_terms"], "pcodes": c["pcodes"], "named_pids": c["named_pids"],
            "candidates": ";".join(sorted(c.get("candidates", {}))), "cue_sentence": c["cue_sentence"]}
