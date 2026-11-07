"""Cue lists and source resolution (Methodology Note 3, steps 1 and 3).

* :data:`REPLICATION_CUES`, :data:`SCALING_CUES` - the Appendix starting lists
  (English, with French / Spanish / Portuguese equivalents).
* :data:`FAMILY_CUES` - language that declares a project family
  (AF, parent, phase, series, MPA, successor), used to find family edges.
* :class:`AliasIndex` - maps project names, acronyms and P-codes to project IDs.
  Built from ``projects.csv`` plus every "Name (ACRONYM, P123456)" pattern found
  in the corpus, so sources outside the portfolio can be resolved too.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

PCODE_RE = re.compile(r"\bP\d{6}\b")

REPLICATION_CUES = [
    r"replicat\w*", r"replicable",
    r"based on (?:the |a )?(?:experience|success|model|lessons|approach|results|achievements|design)",
    r"modell?ed (?:on|after)", r"build(?:s|ing)? (?:up)?on (?:the |a )?(?:experience|success|lessons|achievements|results|model|approach|work)",
    r"draw(?:s|ing)? on (?:the )?(?:lessons|experience)", r"adapted from", r"inspired by",
    r"similar to (?:the )?(?:approach|model|system|project)", r"lessons (?:learned |learnt )?from",
    r"following the example of", r"successful experience", r"piloted (?:in|under|by)", r"proven (?:model|approach)",
    # French / Spanish / Portuguese
    r"r[ée]pliqu\w+", r"s'inspir\w+", r"sur la base de l'exp[ée]rience", r"replica\w*", r"basad[oa] en la experiencia",
    r"com base na experi[êe]ncia",
]
SCALING_CUES = [
    r"scal(?:e|es|ed|ing)[- ]?up", r"additional financing", r"restructuring to expand",
    r"phase (?:ii|iii|2|3|4|two|three)\b", r"(?:second|third|next|subsequent) phase",
    r"multi-?phase programmatic approach", r"\bMPA\b", r"series of projects", r"\bSOP ?[2-9]\b",
    r"follow-?on (?:project|operation)", r"successor (?:project|operation)",
    r"extend(?:ed|ing)? to all", r"nation-?wide", r"national(?:ly)? roll-?out", r"roll(?:ed|ing)?[- ]out (?:to|across|nationally)",
    r"expand(?:ed|ing|s)? (?:its |the )?coverage", r"expansion (?:of|to) (?:the )?(?:system|platform|coverage|program)",
    # French / Spanish / Portuguese
    r"mise à l'échelle", r"passage à l'échelle", r"financement additionnel", r"deuxième phase", r"échelle nationale",
    r"financiamiento adicional", r"ampliaci[óo]n", r"escalamiento", r"financiamento adicional", r"expans[ãa]o",
]
FAMILY_CUES = [
    r"additional financing", r"\bAF ?\d?\b", r"parent project", r"original project", r"restructur\w+",
    r"\bphase\s*(?:[1-9]|i{1,3}|iv|one|two|three|four)\b", r"(?:first|second|third|fourth|previous|earlier|next|subsequent) phase",
    r"\bSOP ?\d\b", r"series of projects", r"multi-?phase programmatic", r"\bMPA\b", r"successor", r"predecessor",
    r"follow-?(?:on|up) (?:project|operation)", r"\b(?:II|III|IV)\b", r"\b[23]\.0\b",
]


def _compile(items: list[str]) -> re.Pattern:
    return re.compile("(" + "|".join(items) + ")", re.IGNORECASE)


REPLICATION_RE = _compile(REPLICATION_CUES)
SCALING_RE = _compile(SCALING_CUES)
FAMILY_RE = re.compile("(" + "|".join(FAMILY_CUES[:-2]) + ")", re.IGNORECASE)  # roman numerals only in names


@dataclass
class CueHit:
    replication: list[str] = field(default_factory=list)
    scaling: list[str] = field(default_factory=list)
    pcodes: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)   # resolved P-codes found through names / acronyms

    @property
    def any(self) -> bool:
        return bool(self.replication or self.scaling or self.pcodes or self.names)

    def families(self) -> list[str]:
        out = []
        if self.replication:
            out.append("replication")
        if self.scaling:
            out.append("scaling")
        if self.pcodes or self.names:
            out.append("source_identifier")
        return out


def scan(text: str, own_pid: str, aliases: "AliasIndex | None" = None, need_names: bool = False) -> CueHit:
    """Step 1 on one sentence."""
    h = CueHit()
    h.replication = sorted({m.group(0).lower() for m in REPLICATION_RE.finditer(text)})
    h.scaling = sorted({m.group(0).lower() for m in SCALING_RE.finditer(text)})
    h.pcodes = sorted(set(PCODE_RE.findall(text)) - {own_pid})
    if aliases is not None and (h.replication or h.scaling or need_names):
        h.names = sorted({pid for pid, _ in aliases.find_in(text) if pid != own_pid and pid not in h.pcodes})
    return h


# ----------------------------------------------------------------------------
# Alias index
# ----------------------------------------------------------------------------
_NAME_BEFORE_PCODE = re.compile(
    r"((?:[A-Z][\w'’\-&]*|of|and|for|the|in|to|de|du|des|la|le|et|y|e)(?:[ \-](?:[A-Z][\w'’\-&]*|of|and|for|the|in|to|de|du|des|la|le|et|y|e)){1,14})"
    r"\s*[\(\[–—-]\s*(?:([A-Z][A-Za-z0-9\-]{1,14})\s*[,;]?\s*)?(P\d{6})")
_ACRONYM_THEN_PCODE = re.compile(r"\b([A-Z][A-Z0-9\-]{2,14}(?: ?(?:II|III|IV|[1-4]|SOP ?\d))?)\s*[\(,–—-]\s*(P\d{6})\b")
_STOP_ALIASES = {"IDA", "IBRD", "PAD", "PID", "ISR", "ICR", "AF", "MPA", "SOP", "IPF", "PFOR", "PFORR", "DPO", "DPF",
                 "CERC", "GEF", "TA", "PIU", "PCU", "PMU", "US", "USD", "THE", "WB", "WBG", "COVID", "COVID-19", "IFC"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", s.lower())).strip()


@dataclass
class AliasIndex:
    """name / acronym -> project ID, with vote counts so ambiguous aliases can be dropped."""
    votes: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    names: dict[str, str] = field(default_factory=dict)       # pid -> best known long name
    _compiled: list[tuple[re.Pattern, str, str]] | None = None

    def add(self, alias: str, pid: str, weight: int = 1) -> None:
        a = alias.strip(" ,;:-–—()")
        if len(a) < 3 or a.upper() in _STOP_ALIASES:
            return
        self.votes[_norm(a) if " " in a else a][pid] += weight
        self._compiled = None

    @classmethod
    def build(cls, projects: dict, sentences_by_pid: dict) -> "AliasIndex":
        idx = cls()
        for pid, p in projects.items():
            if p.project_name:
                idx.add(p.project_name, pid, 5)
                idx.names[pid] = p.project_name
        for pid, sents in sentences_by_pid.items():
            for s in sents:
                if "P" not in s.text:
                    continue
                for m in _NAME_BEFORE_PCODE.finditer(s.text):
                    name, acr, code = m.group(1), m.group(2), m.group(3)
                    words = name.split()
                    # keep the trailing run that looks like a title (starts with a capital)
                    while words and not words[0][:1].isupper():
                        words.pop(0)
                    if len(words) >= 3:
                        idx.add(" ".join(words), code)
                        idx.names.setdefault(code, " ".join(words))
                    if acr:
                        idx.add(acr, code)
                for m in _ACRONYM_THEN_PCODE.finditer(s.text):
                    idx.add(m.group(1), m.group(2))
        return idx

    def resolved(self) -> dict[str, str]:
        """alias -> pid where one project holds >= 75% of the votes."""
        out = {}
        for a, c in self.votes.items():
            pid, n = c.most_common(1)[0]
            if n / sum(c.values()) >= 0.75:
                out[a] = pid
        return out

    def _patterns(self):
        """Two combined regexes (names: case-insensitive, acronyms: case-sensitive) plus lookup tables."""
        if self._compiled is None:
            res = self.resolved()
            names = {a: pid for a, pid in res.items() if " " in a}
            acrs = {a: pid for a, pid in res.items() if " " not in a}
            name_rx = re.compile(r"\b(" + "|".join(r"\W+".join(map(re.escape, a.split())) for a in sorted(names, key=len, reverse=True)) + r")\b",
                                 re.IGNORECASE) if names else None
            acr_rx = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(acrs, key=len, reverse=True))) + r")(?![\w-])") if acrs else None
            self._compiled = (name_rx, names, acr_rx, acrs)
        return self._compiled

    def find_in(self, text: str) -> list[tuple[str, str]]:
        name_rx, names, acr_rx, acrs = self._patterns()
        out = []
        if name_rx is not None:
            for m in name_rx.finditer(text):
                key = _norm(m.group(0))
                if key in names:
                    out.append((names[key], key))
        if acr_rx is not None:
            for m in acr_rx.finditer(text):
                if m.group(0) in acrs:
                    out.append((acrs[m.group(0)], m.group(0)))
        return out

    def resolve(self, source_text: str, own_pid: str = "") -> tuple[str, str]:
        """Step 3: P-code first, then project name / acronym. Returns (pid, method)."""
        if not source_text:
            return "", ""
        codes = [c for c in PCODE_RE.findall(source_text) if c != own_pid]
        if codes:
            return codes[0], "pcode"
        hits = [(pid, a) for pid, a in self.find_in(source_text) if pid != own_pid]
        if hits:
            hits.sort(key=lambda t: -len(t[1]))  # longest alias wins
            return hits[0][0], "name" if " " in hits[0][1] else "acronym"
        return "", ""
