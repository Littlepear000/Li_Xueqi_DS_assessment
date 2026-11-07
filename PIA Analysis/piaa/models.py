"""Data model shared by the workflow, the runner, the export and (later) the web app.

Everything is a plain dataclass with ``to_dict`` so it serialises to JSON for
the SQLite layer and to rows for the Excel export.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Evidence:
    """A verbatim passage anchored to a document."""

    guid: str
    doc_type: str
    doc_date: str
    file_name: str
    char_start: int
    char_end: int
    text: str
    match_kind: str = "exact"
    similarity: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Attribute:
    """One classified attribute of an approach with its provenance."""

    value: str
    code: str = ""          # e.g. pillar id "P3", solution id "S6"
    confidence: float | None = None
    rationale: str = ""
    validated: str = ""     # "" | "confirmed" | "revised" | "rejected"
    validation_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplicationLink:
    other_project_id: str
    other_approach_id: str | None
    kind: str              # explicit_reference | similar_approach
    score: float
    direction: str         # "replicates" (this is later) | "replicated_by" (this is earlier) | "unknown"
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Approach:
    approach_id: str                       # f"{project_id}-A{n}"
    project_id: str
    name: str
    description: str
    evidence: Evidence
    why_innovative: str = ""
    category: Attribute | None = None       # pillar
    category_solution: Attribute | None = None
    sector: Attribute | None = None
    theme: Attribute | None = None
    replication: list[ReplicationLink] = field(default_factory=list)
    extra_evidence: list[Evidence] = field(default_factory=list)
    status: str = "generated"               # generated | validated | rejected | referenced_only | mentioned_only
    adoption: Attribute | None = None       # value: applied | mentioned ; code: mention_for category (workflow v3+)
    replication_verdict: str = ""           # reviewer: "" | confirmed | rejected (+ note), set in the web app
    innovation_basis: str = ""              # workflow v6+: what is new (product / service / process / delivery / organisation) and the words that show it
    innovation_cues: list[str] = field(default_factory=list)   # v6+: innovation-dictionary hits (non-technology) in its evidence units

    def to_dict(self) -> dict:
        return {
            "approach_id": self.approach_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "why_innovative": self.why_innovative,
            "evidence": self.evidence.to_dict(),
            "extra_evidence": [e.to_dict() for e in self.extra_evidence],
            "category": self.category.to_dict() if self.category else None,
            "category_solution": self.category_solution.to_dict() if self.category_solution else None,
            "sector": self.sector.to_dict() if self.sector else None,
            "theme": self.theme.to_dict() if self.theme else None,
            "replication": [r.to_dict() for r in self.replication],
            "status": self.status,
            "adoption": self.adoption.to_dict() if self.adoption else None,
            "replication_verdict": self.replication_verdict,
            "innovation_basis": self.innovation_basis,
            "innovation_cues": self.innovation_cues,
        }


@dataclass
class StepTrace:
    step: str
    started_at: str
    ended_at: str = ""
    status: str = "ok"      # ok | skipped | failed
    note: str = ""
    llm_calls: int = 0
    input_chars: int = 0
    output: dict = field(default_factory=dict)   # step-specific details (keyword hits, raw json ...)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectRecord:
    """The result of running one workflow on one project."""

    project_id: str
    workflow: str
    workflow_hash: str
    run_id: str
    started_at: str
    ended_at: str = ""
    input_fingerprint: str = ""
    innovation_tier: str = ""               # High | Moderate | Low
    innovation_keyword_hits: int = 0
    innovative: str = ""                    # Yes | No | Unclear
    approaches: list[Approach] = field(default_factory=list)
    documents_used: list[dict] = field(default_factory=list)
    trace: list[StepTrace] = field(default_factory=list)
    error: str = ""
    aec_rows: list[dict] = field(default_factory=list)        # Approach Evidence Corpus rows (workflow v2+)
    exclusion_log: list[dict] = field(default_factory=list)   # candidates rejected, with reasons
    llm_usage: dict = field(default_factory=dict)             # calls, tokens and list-price cost estimate for this run
    workflow_tag: str = ""                  # release tag of the workflow folder, e.g. v1.1 (v1.1+dev = unreleased edits)
    package_version: str = ""               # piaa.__version__ at run time

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "workflow": self.workflow,
            "workflow_tag": self.workflow_tag,
            "workflow_hash": self.workflow_hash,
            "package_version": self.package_version,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "input_fingerprint": self.input_fingerprint,
            "innovation_tier": self.innovation_tier,
            "innovation_keyword_hits": self.innovation_keyword_hits,
            "innovative": self.innovative,
            "n_approaches": len(self.approaches),
            "approaches": [a.to_dict() for a in self.approaches],
            "documents_used": self.documents_used,
            "trace": [t.to_dict() for t in self.trace],
            "error": self.error,
            "aec_rows": self.aec_rows,
            "exclusion_log": self.exclusion_log,
            "llm_usage": self.llm_usage,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def fingerprint(parts: list[Any]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]
