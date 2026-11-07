"""Project families (Methodology Note 3, "Family is the decisive test").

A family is a project with its Additional Financing and restructurings, plus
the phases / successors that its documents or metadata declare as one series.
Edges come from two places:

* **metadata** - ``projects.csv`` names such as ``"P169698 (AF 1)"`` (AF of
  P169698) and names that differ only by a phase marker (``"... - Phase 3"`` /
  ``"... - Phase 4"``, ``"LLRP"`` / ``"LLRP II"``, ``"SOP1"`` / ``"SOP2"``);
* **documents** - sentences where another P-code sits next to family language,
  confirmed by the model (``additional_financing`` or ``series`` relation).

Families are the connected components of these edges; the family ID is
``F-<earliest member>``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_AF_NAME = re.compile(r"^\s*(P\d{6})\s*\(\s*AF\s*\d*\s*\)", re.IGNORECASE)
_PHASE_TOKENS = re.compile(
    r"(\(?\bAF\s*\d*\)?|\bphase\s*(?:[0-9]+|i{1,3}|iv|one|two|three|four)\b|\bSOP\s*-?\s*\d\b|\bseries\b|"
    r"\b(?:II|III|IV)\b|\b[2-4](?:\.0)?\b|\b[2-4]\b)", re.IGNORECASE)


def name_stem(name: str) -> str:
    s = _PHASE_TOKENS.sub(" ", name or "")
    s = re.sub(r"[^\w ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Edge:
    a: str
    b: str
    kind: str            # additional_financing | series
    origin: str          # metadata_name | metadata_stem | document
    evidence: str = ""
    doc_id: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Families:
    edges: list[Edge] = field(default_factory=list)
    parent: dict[str, str] = field(default_factory=dict)
    approval: dict[str, str] = field(default_factory=dict)

    def _find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def add(self, e: Edge) -> None:
        if e.a == e.b:
            return
        self.edges.append(e)
        ra, rb = self._find(e.a), self._find(e.b)
        if ra != rb:
            self.parent[ra] = rb

    def family_id(self, pid: str) -> str:
        root = self._find(pid)
        members = [p for p in list(self.parent) if self._find(p) == root]
        first = min(members, key=lambda p: (self.approval.get(p) or "9999", p))
        return f"F-{first}"

    def same_family(self, a: str, b: str) -> bool:
        return bool(a and b) and (a == b or self._find(a) == self._find(b))

    def edge_kind(self, a: str, b: str) -> str:
        """Kind of the direct edge between two members, or 'series' for an indirect relation."""
        if a == b:
            return "self"
        for e in self.edges:
            if {e.a, e.b} == {a, b}:
                return e.kind
        return "series" if self.same_family(a, b) else ""

    def af_parent(self, pid: str) -> str:
        """Parent project when ``pid`` is an AF / restructuring with its own P-code (edge a=AF, b=parent)."""
        for e in self.edges:
            if e.kind == "additional_financing" and e.a == pid and e.origin != "document":
                return e.b
        for e in self.edges:  # document edges are stored as (this project, other) with relation this_is_af_of
            if e.kind == "additional_financing" and e.a == pid and e.evidence.startswith("this_is_af_of"):
                return e.b
        return ""

    def members(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in list(self.parent):
            out.setdefault(self.family_id(p), []).append(p)
        return {k: sorted(v, key=lambda p: (self.approval.get(p) or "9999", p)) for k, v in out.items()}


def from_metadata(projects: dict) -> Families:
    fam = Families()
    for pid, p in projects.items():
        fam.approval[pid] = p.approval_date
        fam._find(pid)
    for pid, p in projects.items():
        m = _AF_NAME.match(p.project_name or "")
        if m:
            fam.add(Edge(pid, m.group(1), "additional_financing", "metadata_name", p.project_name))
    stems: dict[str, list[str]] = {}
    for pid, p in projects.items():
        if _AF_NAME.match(p.project_name or ""):
            continue
        st = name_stem(p.project_name)
        if len(st) >= 4 and _PHASE_TOKENS.search(p.project_name or "") is not None:
            stems.setdefault(st, []).append(pid)
    # also allow a phased name to meet its un-phased first phase ("LLRP" / "LLRP II")
    for pid, p in projects.items():
        st = name_stem(p.project_name)
        if st in stems and pid not in stems[st]:
            stems[st].append(pid)
    for st, pids in stems.items():
        for other in pids[1:]:
            fam.add(Edge(pids[0], other, "series", "metadata_stem",
                         f"{projects[pids[0]].project_name} / {projects[other].project_name}"))
    return fam
