"""Shared context object passed to every workflow step."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..catalog import Project
from ..config import Settings
from ..documents import DocumentIndex, DocumentRef
from ..llm import LLMClient
from ..models import ProjectRecord, StepTrace, now_iso


@dataclass
class RunContext:
    settings: Settings
    workflow: "Workflow"  # noqa: F821  (piaa.workflows.Workflow)
    project: Project
    index: DocumentIndex
    llm: LLMClient
    record: ProjectRecord
    portfolio: "PortfolioStore"  # noqa: F821  (piaa.replication.PortfolioStore)
    docs: list[DocumentRef] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    lock: object = None  # shared RLock guarding the portfolio store during parallel runs
    sentences: dict = field(default_factory=dict)      # v2: guid -> list[Sentence]
    candidates: list = field(default_factory=list)     # v2: candidate sentences for classification
    units: list = field(default_factory=list)          # v5: reading units of the primary document

    def step(self, name: str) -> StepTrace:
        t = StepTrace(step=name, started_at=now_iso())
        self.record.trace.append(t)
        return t

    def finish(self, t: StepTrace, status: str = "ok", note: str = "", **output) -> None:
        t.ended_at = now_iso()
        t.status = status
        t.note = note
        t.llm_calls = sum(1 for c in self.llm.calls if c.step == t.step)
        t.input_chars = sum(c.input_chars for c in self.llm.calls if c.step == t.step)
        if t.llm_calls:
            from ..llm import usage_summary
            t.output["usage"] = usage_summary([c for c in self.llm.calls if c.step == t.step])
        if output:
            t.output.update(output)
        self.log.append(f"[{t.step}] {status} {note}".strip())

    def cfg(self, key: str, default=None):
        return self.workflow.config.get(key, default)
