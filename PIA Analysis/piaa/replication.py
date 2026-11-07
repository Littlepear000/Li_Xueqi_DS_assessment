"""Portfolio-level replication detection.

Two signals, both cheap enough to run incrementally as each project is processed:

1. **Explicit reference** - the project's documents mention another in-scope
   project (by P-code or by name) close to replication language
   ("builds on", "replicates", "scaled from", "lessons from", "parent project",
   "additional financing" ...).
2. **Similar approach** - TF-IDF cosine similarity between the approach text
   (name + description + evidence) and every approach already stored for
   *other* projects. Links above the threshold are kept with their score.

Direction uses approval dates: the earlier project is treated as the origin,
the later one as the replication. The store is a JSON file under
``output_dir/cache/portfolio_approaches.json`` so it survives between runs and
can be rebuilt from the database later.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import ReplicationLink

PCODE_RE = re.compile(r"\bP\d{6}\b")
REPLICATION_LANGUAGE = re.compile(
    r"\b(build(?:s|ing)? on|replicat\w*|scal(?:e|es|ed|ing)[- ]up|scaled from|lessons? (?:learned )?from|"
    r"follow(?:s|ing)?[- ]on|parent project|additional financing|modell?ed on|adapted from|based on the experience|"
    r"draw(?:s|ing)? on|extend(?:s|ing)? the|successor|second phase|phase ii|series of projects)\b",
    re.IGNORECASE,
)


@dataclass
class StoredApproach:
    approach_id: str
    project_id: str
    approval_date: str
    text: str
    name: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PortfolioStore:
    path: Path
    approaches: dict[str, StoredApproach] = field(default_factory=dict)
    project_names: dict[str, str] = field(default_factory=dict)  # project_id -> name (for explicit refs)
    approval_dates: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "PortfolioStore":
        store = cls(Path(path))
        if store.path.exists():
            data = json.loads(store.path.read_text(encoding="utf-8"))
            store.approaches = {k: StoredApproach(**v) for k, v in data.get("approaches", {}).items()}
            store.project_names = data.get("project_names", {})
            store.approval_dates = data.get("approval_dates", {})
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "approaches": {k: v.to_dict() for k, v in self.approaches.items()},
            "project_names": self.project_names, "approval_dates": self.approval_dates,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    def register_projects(self, projects: dict) -> None:
        for pid, p in projects.items():
            self.project_names[pid] = p.project_name
            self.approval_dates[pid] = p.approval_date

    def upsert(self, approach_id: str, project_id: str, approval_date: str, name: str, text: str) -> None:
        self.approaches[approach_id] = StoredApproach(approach_id, project_id, approval_date, text, name)

    def drop_project(self, project_id: str) -> None:
        for k in [k for k, v in self.approaches.items() if v.project_id == project_id]:
            del self.approaches[k]

    # ------------------------------------------------------------------
    def _direction(self, this_pid: str, other_pid: str) -> str:
        a, b = self.approval_dates.get(this_pid, ""), self.approval_dates.get(other_pid, "")
        if not a or not b or a == b:
            return "unknown"
        return "replicates" if a > b else "replicated_by"

    def explicit_references(self, project_id: str, text: str, window: int = 300) -> list[ReplicationLink]:
        """Find other in-scope projects mentioned near replication language."""
        links: dict[str, ReplicationLink] = {}
        low = text.lower()
        # 1) P-codes
        for m in PCODE_RE.finditer(text):
            other = m.group(0)
            if other == project_id or other not in self.project_names:
                continue
            s, e = max(0, m.start() - window), min(len(text), m.end() + window)
            ctx = text[s:e]
            has_lang = bool(REPLICATION_LANGUAGE.search(ctx))
            score = 0.9 if has_lang else 0.5
            if other not in links or links[other].score < score:
                links[other] = ReplicationLink(other, None, "explicit_reference", score,
                                               self._direction(project_id, other), ctx.strip()[:400])
        # 2) project names (only reasonably specific names, >= 3 words)
        for other, name in self.project_names.items():
            if other == project_id or other in links or not name or len(name.split()) < 3:
                continue
            i = low.find(name.lower())
            if i < 0:
                continue
            s, e = max(0, i - window), min(len(text), i + len(name) + window)
            ctx = text[s:e]
            has_lang = bool(REPLICATION_LANGUAGE.search(ctx))
            links[other] = ReplicationLink(other, None, "explicit_reference", 0.8 if has_lang else 0.4,
                                           self._direction(project_id, other), ctx.strip()[:400])
        return sorted(links.values(), key=lambda l: -l.score)

    def similar_approaches(self, approach_id: str, project_id: str, text: str,
                           threshold: float = 0.45, max_links: int = 5) -> list[ReplicationLink]:
        """TF-IDF cosine similarity against approaches of *other* projects."""
        others = [a for a in self.approaches.values() if a.project_id != project_id]
        if not others:
            return []
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:  # pragma: no cover
            return _jaccard_fallback(approach_id, project_id, text, others, threshold, max_links, self)
        corpus = [text] + [a.text for a in others]
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        X = vec.fit_transform(corpus)
        sims = cosine_similarity(X[0:1], X[1:]).ravel()
        pairs = sorted(zip(sims, others), key=lambda t: -t[0])
        links = []
        for s, a in pairs[:max_links]:
            if s < threshold:
                break
            links.append(ReplicationLink(a.project_id, a.approach_id, "similar_approach", float(round(s, 3)),
                                         self._direction(project_id, a.project_id), a.name))
        return links


def _jaccard_fallback(approach_id, project_id, text, others, threshold, max_links, store):
    def toks(s):
        return set(re.findall(r"[a-z]{3,}", s.lower()))
    t = toks(text)
    scored = []
    for a in others:
        o = toks(a.text)
        if not t or not o:
            continue
        scored.append((len(t & o) / len(t | o), a))
    scored.sort(key=lambda x: -x[0])
    return [ReplicationLink(a.project_id, a.approach_id, "similar_approach", round(s, 3),
                            store._direction(project_id, a.project_id), a.name)
            for s, a in scored[:max_links] if s >= threshold]


def rescan(store: PortfolioStore, threshold: float = 0.45, max_links: int = 5) -> dict[str, list[ReplicationLink]]:
    """Recompute similarity links for every stored approach (final pass)."""
    out = {}
    for a in store.approaches.values():
        out[a.approach_id] = store.similar_approaches(a.approach_id, a.project_id, a.text, threshold, max_links)
    return out
