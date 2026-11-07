"""On-demand, formatted reading context around an evidence span.

The corpus files are single-line text dumps, so reading "one or two pages
around the sentence" needs reconstruction: this module cuts a window of N
pages (~3,200 characters each) around the span, rebuilds paragraph structure
(numbered paragraphs, section headings, lettered sub-points, bullets), and
marks what the reviewer needs to see at a glance:

* the evidence sentence itself (primary highlight),
* other coded sentences of the same project in the window (secondary),
* approach-specific keyword hits (bold).

It also tags paragraphs that carry *forward-looking / aspirational* wording
("will explore", "could", "in the future", "lessons from ...") so that the
reviewer can tell an applied approach from one that is only mentioned - the
distinction workflow v3 makes explicit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .documents import DocumentRef, read_text
from .taxonomy import ddat

PAGE_CHARS = 3200

_PARA_NUM = re.compile(r"(?<=[.:;)\]])\s+(?=(?:\d{1,3}|[ivxIVX]{1,5})\.\s+[A-Z])")
_SUBPOINT = re.compile(r"\s+(?=\([a-z]{1,2}\)\s|\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\)\s|•\s|▪\s|-\s[A-Z])")
_HEADING = re.compile(r"^(?:[A-Z]{1,4}\.|[IVX]{1,5}\.|\d{1,2}\.)?\s*(?:[A-Z][A-Z0-9 ,&/()'-]{6,}|[A-Z][a-z]+(?: [A-Z][a-z]+){1,7})(?::|$)")
_ALLCAPS = re.compile(r"^[A-Z0-9][A-Z0-9 ,&/()'-]{8,}$")
_COMPONENT = re.compile(r"^(Component|Sub-?component|Pillar|Window|Part|Annex|Section|Appendix)\b", re.IGNORECASE)
_ASPIRATION = re.compile(
    r"\b(could|may|might|would|aim(?:s|ed)? to|aspir\w+|vision|envisage\w*|envision\w*|in the (?:medium|long)[- ]term|"
    r"in the future|future (?:phases?|projects?|operations?)|is expected to|potential(?:ly)?|explore\w*|consider\w*|"
    r"lessons? (?:learned|learnt|from)|other (?:countries|projects|programs|programmes)|international experience|"
    r"global (?:experience|evidence)|best practice|government(?:'s)? (?:plan|strategy|vision)|national strategy|"
    r"not (?:yet )?(?:started|financed|funded)|outside the (?:scope|project)|parallel financing|other donors?)\b", re.IGNORECASE)
_COMMITMENT = re.compile(
    r"\b(the project will|this (?:sub)?component will|will (?:finance|fund|support|establish|develop|deploy|procure|build|implement|pilot|roll out|scale)|"
    r"financ(?:es|ed|ing) (?:the|a|an)|is financing|has (?:been )?(?:procured|deployed|rolled out|launched|established|developed)|"
    r"was (?:procured|deployed|rolled out|launched|established|developed|completed)|is operational|went live|disbursement[- ]linked|DLI|"
    r"results indicator|intermediate results? indicator|PDO indicator|legal covenant|prior action|cost(?:ed)? at|US\$[\d.,]+ ?(?:million|m\b))\b", re.IGNORECASE)


@dataclass
class Block:
    kind: str                 # heading | para | subpoint | bullet
    start: int
    end: int
    text: str
    marks: list[dict] = field(default_factory=list)   # {start,end,kind} relative to block text
    signals: dict = field(default_factory=dict)       # aspiration / commitment phrase counts

    def to_dict(self) -> dict:
        return {"kind": self.kind, "char_start": self.start, "char_end": self.end, "text": self.text, "marks": self.marks, "signals": self.signals}


def _split_blocks(text: str, base: int) -> list[Block]:
    """Rebuild paragraph structure inside a window."""
    pieces: list[tuple[int, int]] = []
    pos = 0
    for m in _PARA_NUM.finditer(text):
        if m.start() > pos:
            pieces.append((pos, m.start()))
        pos = m.end()
    pieces.append((pos, len(text)))
    blocks: list[Block] = []
    for s, e in pieces:
        chunk = text[s:e]
        # split lettered sub-points / bullets inside a paragraph
        sub_pos = 0
        subs: list[tuple[int, int]] = []
        for m in _SUBPOINT.finditer(chunk):
            if m.start() > sub_pos:
                subs.append((sub_pos, m.start()))
            sub_pos = m.end()
        subs.append((sub_pos, len(chunk)))
        for i, (a, b) in enumerate(subs):
            t = chunk[a:b].strip()
            if not t:
                continue
            lead = chunk[a:b].find(t)
            gs, ge = base + s + a + lead, base + s + a + lead + len(t)
            if i == 0 and (len(t) < 90 and (_ALLCAPS.match(t) or _COMPONENT.match(t) or _HEADING.match(t))):
                kind = "heading"
            elif i > 0 and re.match(r"^\((?:[a-z]{1,2}|i{1,3}|iv|v|vi{0,3}|ix|x)\)", t):
                kind = "subpoint"
            elif i > 0:
                kind = "bullet"
            else:
                kind = "para"
            blocks.append(Block(kind, gs, ge, t))
    return blocks


def build_context(doc: DocumentRef, start: int, end: int, pages: int = 2, project_rows: list[dict] | None = None,
                  approach_code: str | None = None) -> dict:
    """Return a formatted window of ``pages`` pages centred on [start, end)."""
    text = read_text(doc.path)
    half = max(1, pages) * PAGE_CHARS // 2
    ws, we = max(0, start - half), min(len(text), end + half)
    # snap to sentence boundaries
    m = re.search(r"[.!?]\s", text[max(0, ws - 400):ws])
    if m:
        ws = max(0, ws - 400) + m.end()
    m = re.search(r"[.!?]\s", text[we:we + 400])
    if m:
        we = we + m.end()
    window = text[ws:we]
    blocks = _split_blocks(window, ws)
    # keyword patterns for the approach (bold) and other coded rows (secondary)
    kw = [p for p in ddat.patterns() if (approach_code is None or p.code == approach_code)]
    others = [(r["char_start"], r["char_end"], r.get("approach_code", ""), r.get("evidence_level", "")) for r in (project_rows or [])
              if r.get("doc_id") == doc.guid and not (r["char_end"] <= ws or r["char_start"] >= we)]
    for b in blocks:
        marks = []
        # primary evidence
        if not (end <= b.start or start >= b.end):
            marks.append({"start": max(0, start - b.start), "end": min(len(b.text), end - b.start), "kind": "evidence"})
        for os_, oe, code, lvl in others:
            if (os_, oe) == (start, end) or oe <= b.start or os_ >= b.end:
                continue
            marks.append({"start": max(0, os_ - b.start), "end": min(len(b.text), oe - b.start), "kind": "coded", "code": code, "level": lvl})
        for p in kw[:200]:
            for mm in p.regex.finditer(b.text):
                marks.append({"start": mm.start(), "end": mm.end(), "kind": "keyword", "term": p.term})
        b.marks = sorted(marks, key=lambda x: (x["start"], -x["end"]))
        asp = _ASPIRATION.findall(b.text)
        com = _COMMITMENT.findall(b.text)
        b.signals = {"aspiration": len(asp), "commitment": len(com),
                     "aspiration_terms": sorted({a.lower() if isinstance(a, str) else a[0].lower() for a in asp})[:6],
                     "commitment_terms": sorted({c.lower() if isinstance(c, str) else c[0].lower() for c in com})[:6]}
    page_of = lambda pos: int((pos - ws) // PAGE_CHARS) + 1
    return {
        "guid": doc.guid, "file_name": doc.file_name, "doc_type": doc.doc_type, "doc_date": doc.doc_date,
        "doc_length": len(text), "window_start": ws, "window_end": we, "pages": pages, "page_chars": PAGE_CHARS,
        "position_pct": round(100 * start / max(1, len(text)), 1),
        "evidence": {"char_start": start, "char_end": end, "text": text[start:end], "verified": True},
        "blocks": [{**b.to_dict(), "page": page_of(b.start)} for b in blocks],
        "coded_in_window": len(others),
    }
