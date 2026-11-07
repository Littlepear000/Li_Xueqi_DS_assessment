"""Index and read project documents.

File-name convention of the corpus::

    {project_id}_{doc_type}_{YYYY-MM-DD}_{guid}.txt

The trailing ``guid`` equals the document ID in the World Bank Documents &
Reports API, so a local file and an API record can always be reconciled.

Verbatim guarantee
------------------
Every evidence sentence the pipeline stores is anchored to a document by
``(guid, char_start, char_end)``. :func:`locate_span` finds a sentence in the
document text (exact match first, whitespace-insensitive match second, fuzzy
match last) and :func:`verify_span` re-reads the file to confirm that the
stored text still matches the offsets. A record whose evidence cannot be
located is rejected rather than stored.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

FILENAME_RE = re.compile(r"^(P\d{6})_([A-Za-z]+)_(\d{4}-\d{2}-\d{2})_(\d+)\.txt$")

# Priority used when a workflow asks for "the primary document".
DOC_TYPE_PRIORITY = ["PAD", "ProjectPaper", "PID", "ICR", "ISR"]


@dataclass
class DocumentRef:
    project_id: str
    doc_type: str
    doc_date: str
    guid: str
    path: Path
    source: str = "local"  # "local" | "api"

    @property
    def file_name(self) -> str:
        return self.path.name

    def to_dict(self) -> dict:
        return {"project_id": self.project_id, "doc_type": self.doc_type, "doc_date": self.doc_date,
                "guid": self.guid, "file_name": self.file_name, "source": self.source}


@dataclass
class DocumentIndex:
    by_project: dict[str, list[DocumentRef]] = field(default_factory=dict)

    def for_project(self, project_id: str) -> list[DocumentRef]:
        docs = list(self.by_project.get(project_id, []))
        docs.sort(key=lambda d: (DOC_TYPE_PRIORITY.index(d.doc_type) if d.doc_type in DOC_TYPE_PRIORITY else 99, d.doc_date))
        return docs

    def by_guid(self, guid: str) -> DocumentRef | None:
        for docs in self.by_project.values():
            for d in docs:
                if d.guid == guid:
                    return d
        return None

    def summary(self) -> dict:
        n_docs = sum(len(v) for v in self.by_project.values())
        types: dict[str, int] = {}
        for docs in self.by_project.values():
            for d in docs:
                types[d.doc_type] = types.get(d.doc_type, 0) + 1
        return {"documents": n_docs, "projects": len(self.by_project), "by_type": types}


def build_index(documents_dirs: list[Path]) -> DocumentIndex:
    """Scan one or more folders; the first folder is treated as the local corpus."""
    idx = DocumentIndex()
    seen: set[str] = set()
    for n, folder in enumerate(documents_dirs):
        folder = Path(folder)
        if not folder.exists():
            continue
        for p in sorted(folder.glob("*.txt")):
            m = FILENAME_RE.match(p.name)
            if not m:
                continue
            pid, dtype, ddate, guid = m.groups()
            if guid in seen:
                continue
            seen.add(guid)
            idx.by_project.setdefault(pid, []).append(
                DocumentRef(pid, dtype, ddate, guid, p, source="local" if n == 0 else "api"))
    return idx


@lru_cache(maxsize=256)
def read_text(path: str | Path) -> str:
    """Read a document as text. The corpus is mostly UTF-8 but a few files are cp1252."""
    data = Path(path).read_bytes()
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


# ----------------------------------------------------------------------------
# Chunking: the files are a single line, so we cut on sentence boundaries.
# ----------------------------------------------------------------------------
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


@dataclass
class Chunk:
    doc: DocumentRef
    start: int
    end: int
    text: str


def chunk_document(doc: DocumentRef, size: int = 6000, overlap: int = 400) -> list[Chunk]:
    text = read_text(doc.path)
    chunks: list[Chunk] = []
    pos = 0
    while pos < len(text):
        end = min(len(text), pos + size)
        if end < len(text):
            # back up to the last sentence boundary inside the window
            window = text[pos:end]
            cut = max((m.end() for m in _SENT_END.finditer(window)), default=None)
            if cut and cut > size * 0.5:
                end = pos + cut
        chunks.append(Chunk(doc, pos, end, text[pos:end]))
        if end >= len(text):
            break
        pos = max(end - overlap, pos + 1)
    return chunks


def sentences_with_offsets(text: str) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for m in _SENT_END.finditer(text):
        out.append((pos, m.start(), text[pos:m.start()]))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text), text[pos:]))
    return out


# ----------------------------------------------------------------------------
# Verbatim anchoring
# ----------------------------------------------------------------------------
@dataclass
class Span:
    guid: str
    start: int
    end: int
    text: str
    match_kind: str  # exact | whitespace | fuzzy
    similarity: float = 1.0

    def to_dict(self) -> dict:
        return {"guid": self.guid, "char_start": self.start, "char_end": self.end, "text": self.text,
                "match_kind": self.match_kind, "similarity": round(self.similarity, 3)}


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def locate_span(doc: DocumentRef, sentence: str, min_similarity: float = 0.85) -> Span | None:
    """Find ``sentence`` in the document and return its exact character span.

    The stored text is always what is *in the file*, never what the model wrote.
    """
    text = read_text(doc.path)
    needle = sentence.strip().strip('"“”')
    if not needle:
        return None
    i = text.find(needle)
    if i >= 0:
        return Span(doc.guid, i, i + len(needle), text[i:i + len(needle)], "exact")
    # whitespace-insensitive search
    pattern = r"\s+".join(re.escape(w) for w in needle.split())
    m = re.search(pattern, text)
    if m:
        return Span(doc.guid, m.start(), m.end(), text[m.start():m.end()], "whitespace")
    # fuzzy: compare against sentences of similar length
    best, best_ratio = None, 0.0
    n_needle = _norm_ws(needle).lower()
    for s, e, sent in sentences_with_offsets(text):
        if abs(len(sent) - len(needle)) > max(80, len(needle)):
            continue
        r = difflib.SequenceMatcher(None, n_needle, _norm_ws(sent).lower()).ratio()
        if r > best_ratio:
            best, best_ratio = (s, e, sent), r
    if best and best_ratio >= min_similarity:
        s, e, sent = best
        return Span(doc.guid, s, e, sent, "fuzzy", best_ratio)
    return None


def verify_span(doc: DocumentRef, span: Span | dict) -> bool:
    """Re-read the file and confirm the stored text is exactly at the stored offsets."""
    if isinstance(span, dict):
        start, end, stored = span["char_start"], span["char_end"], span["text"]
    else:
        start, end, stored = span.start, span.end, span.text
    text = read_text(doc.path)
    return text[start:end] == stored
