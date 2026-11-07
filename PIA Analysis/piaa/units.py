"""Reading units: the smallest piece of a document the extraction workflow reads at once.

Project documents are single-line text dumps of PDFs, so there are no paragraph
breaks to rely on. World Bank appraisal documents do, however, number their
paragraphs ("4. Coronavirus disease ..."). A *reading unit* is therefore:

* one numbered paragraph of the document, when the running paragraph numbers
  can be followed, otherwise
* a window of consecutive sentences of about ``target_chars`` characters.

Units never split a sentence, keep character offsets into the source file (so
every evidence sentence stays verbatim and anchored), and are capped at
``max_chars``; a longer paragraph is cut at a sentence boundary. Very short
units are merged into the following one.

Half a page of a PAD is roughly 1,600 characters; that is the amount of context
added on each side when the validation step asks for more (see workflow v5).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .documents import DocumentRef, read_text
from .segment import Sentence, segment

_PARA_START = re.compile(r"^(\d{1,3})\.\s+(?=[A-Z(\"“])")
_PARA_MARK = re.compile(r"^(\d{1,3})\.$")   # the segmenter isolates "12." as its own fragment before the paragraph text
PAGE_CHARS = 3200  # approximate characters per PAD page (used for "pages" in reviewer tooling)


@dataclass
class Unit:
    unit_id: str                 # "U12"
    doc: DocumentRef
    index: int                   # 0-based unit number within the document
    para_no: int | None          # paragraph number printed in the document, when detected
    sentences: list[Sentence] = field(default_factory=list)
    cues: list[str] = field(default_factory=list)   # keyword cues found in the unit (filled by the workflow)

    @property
    def start(self) -> int:
        return self.sentences[0].start

    @property
    def end(self) -> int:
        return self.sentences[-1].end

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    @property
    def chars(self) -> int:
        return self.end - self.start

    @property
    def boilerplate(self) -> bool:
        return all(s.boilerplate for s in self.sentences)

    def numbered_text(self) -> str:
        """Sentences prefixed with their ids, the form shown to the model."""
        return "\n".join(f"[{self.unit_id}.s{k}] {s.text}" for k, s in enumerate(self.sentences, 1))

    def sentence(self, ref: str) -> Sentence | None:
        """Resolve a model reference such as ``U12.s3`` (also accepts ``s3`` or ``3``)."""
        m = re.search(r"s?(\d+)$", str(ref).strip())
        if not m:
            return None
        k = int(m.group(1))
        return self.sentences[k - 1] if 1 <= k <= len(self.sentences) else None

    def to_dict(self) -> dict:
        return {"unit_id": self.unit_id, "guid": self.doc.guid, "doc_type": self.doc.doc_type, "doc_date": self.doc.doc_date,
                "para_no": self.para_no, "char_start": self.start, "char_end": self.end, "sentences": len(self.sentences),
                "chars": self.chars, "cues": self.cues}


def build_units(doc: DocumentRef, target_chars: int = 1200, max_chars: int = 2400, min_chars: int = 250,
                sentences: list[Sentence] | None = None) -> list[Unit]:
    """Split one document into reading units (numbered paragraphs, else sentence windows)."""
    sents = sentences if sentences is not None else segment(doc)
    groups: list[tuple[int | None, list[Sentence]]] = []
    cur: list[Sentence] = []
    cur_no: int | None = None
    last_no = 0
    for s in sents:
        m = _PARA_START.match(s.text) or _PARA_MARK.match(s.text)
        new_para = False
        if m:
            n = int(m.group(1))
            if last_no < n <= last_no + 3 or (last_no == 0 and n == 1):   # tolerate a missed number, not a footnote digit
                new_para, last_no = True, n
        if cur and (new_para or sum(x.end - x.start for x in cur) >= target_chars and not cur_no):
            groups.append((cur_no, cur))
            cur, cur_no = [], None
        if new_para:
            cur_no = last_no
        cur.append(s)
        if sum(x.end - x.start for x in cur) >= max_chars:          # over-long paragraph: cut at a sentence boundary
            groups.append((cur_no, cur))
            cur, cur_no = [], None
    if cur:
        groups.append((cur_no, cur))
    # a very short group (table notes, a stray fragment) is attached to the previous unit
    merged: list[tuple[int | None, list[Sentence]]] = []
    for no, g in groups:
        if merged and sum(x.end - x.start for x in g) < min_chars and no is None:
            merged[-1] = (merged[-1][0], merged[-1][1] + g)
        elif merged and sum(x.end - x.start for x in merged[-1][1]) < min_chars and merged[-1][0] is None:
            merged[-1] = (no, merged[-1][1] + g)
        else:
            merged.append((no, g))
    return [Unit(f"U{i + 1}", doc, i, no, g) for i, (no, g) in enumerate(merged)]


def expand(unit: Unit, units: list[Unit], chars: int) -> tuple[str, int, int]:
    """Text of ``unit`` with up to ``chars`` characters of the document added on each side
    (whole neighbouring units only). Returns (text, char_start, char_end)."""
    text = read_text(unit.doc.path)
    start, end = unit.start, unit.end
    i = unit.index
    lo, hi = i, i
    while lo > 0 and start - units[lo - 1].start <= chars:
        lo -= 1
        start = units[lo].start
    while hi + 1 < len(units) and units[hi + 1].end - end <= chars:
        hi += 1
        end = units[hi].end
    return text[start:end], start, end
