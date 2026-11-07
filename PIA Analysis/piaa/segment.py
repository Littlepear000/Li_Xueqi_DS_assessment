"""Sentence segmentation with positions (Methodology Note 1, step 1).

Each sentence keeps its character span in the source file so the verbatim
guarantee of :mod:`piaa.documents` still holds, plus its position so the
sentences before and after can be retrieved as context.

The files are single-line text dumps of PDFs, so the segmenter also flags
boilerplate that the coding rules exclude in general: tables of contents
(dot leaders), running headers / page furniture, reference lists and very
short fragments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .documents import DocumentRef, read_text

_SENT_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'“])")
_DOT_LEADER = re.compile(r"\.{4,}|(?:\. ){4,}")
_PAGE_FURNITURE = re.compile(r"^(page \d+( of \d+)?|the world bank .{0,80}\(p\d{6}\)|public disclosure authorized|\d{1,3})$", re.IGNORECASE)
_REFERENCE_LINE = re.compile(r"^(annex|appendix|table \d|figure \d|box \d|source:|note:|http)", re.IGNORECASE)
_BOILERPLATE = re.compile(
    r"grievance redress (mechanism|service)|inspection panel|safeguard|environmental and social (framework|standard|commitment)|"
    r"procurement (plan|regulations?|arrangements?)|disclosure of|anti-?corruption guidelines|financial management (arrangements?|assessment)|"
    r"disbursement (arrangements?|category)|legal covenant|effectiveness condition|retroactive financing", re.IGNORECASE)


@dataclass
class Sentence:
    doc: DocumentRef
    position: int           # sentence number within the document (0-based)
    start: int
    end: int
    text: str
    boilerplate: str = ""   # "" | toc | furniture | reference | short | standard_text

    def to_dict(self) -> dict:
        return {"guid": self.doc.guid, "doc_type": self.doc.doc_type, "doc_date": self.doc.doc_date, "file_name": self.doc.file_name,
                "position": self.position, "char_start": self.start, "char_end": self.end, "text": self.text, "boilerplate": self.boilerplate}


def _flag(text: str) -> str:
    t = text.strip()
    if len(t) < 40:
        return "short"
    if _DOT_LEADER.search(t):
        return "toc"
    if _PAGE_FURNITURE.match(t):
        return "furniture"
    if _REFERENCE_LINE.match(t) and len(t) < 120:
        return "reference"
    if _BOILERPLATE.search(t) and not re.search(r"digital|online|electronic|e-|mobile|data|system|platform|app\b", t, re.IGNORECASE):
        return "standard_text"
    return ""


def segment(doc: DocumentRef, max_len: int = 1200) -> list[Sentence]:
    """Split one document into sentences with character offsets."""
    text = read_text(doc.path)
    out: list[Sentence] = []
    pos = 0
    for m in list(_SENT_END.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        raw = text[pos:end]
        if raw.strip():
            # very long "sentences" (tables, lists) are cut into windows so the model sees manageable pieces
            s = pos
            while s < end:
                e = min(end, s + max_len)
                if e < end:
                    cut = text.rfind(" ", s, e)
                    if cut > s + 200:
                        e = cut
                piece = text[s:e]
                lead = len(piece) - len(piece.lstrip())
                trail = len(piece) - len(piece.rstrip())
                ps, pe = s + lead, e - trail
                if pe > ps:
                    out.append(Sentence(doc, len(out), ps, pe, text[ps:pe], _flag(text[ps:pe])))
                s = e
        pos = m.end() if m else end
    return out


def context(sentences: list[Sentence], i: int) -> tuple[str, str]:
    before = sentences[i - 1].text if i > 0 else ""
    after = sentences[i + 1].text if i + 1 < len(sentences) else ""
    return before, after
