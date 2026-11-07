"""Innovation keyword dictionary.

Source: Appendix B of *Innovation Patterns in the World Bank Group Portfolio*
(working paper in ``background/``). The paper derived 165 terms with two LLMs,
expert review and Python snippet inspection, grouped in seven dimensions, and
scored projects by the number of **distinct** terms hit:

* High     = 4 or more distinct hits
* Moderate = 2-3 distinct hits
* Low      = 0-1 distinct hits

Projects rated High + Moderate form the "innovative subset". We reuse the
dictionary and the thresholds as the screening step (step 0) of the workflow.
Thresholds are configurable per workflow version so sensitivity checks can
vary them by +/-1 as the paper recommends.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DIMENSIONS: dict[str, list[str]] = {
    "innovation": [
        "innovative", "innovation", "innovations", "novel", "novelty", "breakthrough", "cutting-edge",
        "frontier", "transformative", "disruptive", "experimental", "quasiexperimental", "frugal-innovation",
        "good-enough tech", "reverse-innovation",
    ],
    "innovation_cycle": [
        "experimentation", "prototype", "prototyping", "pilot", "pilots", "piloted", "piloting", "sandbox",
        "proof-of-concept", "demo", "demonstration", "demonstrations", "demonstration model", "trial", "trials",
        "beta rollout", "phased rollout", "phased scale-up", "scale-up", "scaled-up", "scaling", "scaling-up",
        "replicate", "replicated", "replication", "mainstream", "mainstreamed", "mainstreaming", "leapfrog",
        "market test", "scaling-readiness", "innovation-ecosystem",
    ],
    "results_based_management": [
        "adaptive", "adaptively", "adaptive management", "learning-by-doing", "feedback loop", "real-time M&E",
        "agile", "agile iteration", "pivot", "course-correct", "A/B test", "randomized trial", "RCT",
        "results-based", "rapid-assessment", "pulse survey", "early-warning", "adaptive logframe",
        "flexible-design", "learning agenda",
    ],
    "innovation_types": [
        "outcome-based", "output-based", "performance-based", "pay-for-results", "PforR", "results-based financing",
        "output-based aid", "blended finance", "blended-financing", "catalytic fund", "guarantee", "guarantees",
        "guaranteed", "risk-sharing", "viability-gap", "PPP", "public-private-partnership", "concession",
        "concessions", "private-capital", "mobilise private", "leverage private", "fintech", "mobile money",
        "mobile banking", "digital payment", "e-wallet",
    ],
    "enabling_technologies": [
        "blockchain", "distributed-ledger", "big data", "data-analytics", "AI", "artificial-intelligence",
        "machine-learning", "predictive model", "drone", "remote-sensing", "satellite imagery", "GIS", "geo-mapping",
        "e-government", "e-service", "e-procurement", "e-bidding", "electronic procurement", "digital platform",
        "cloud-based", "open-data", "API", "interoperability", "telemedicine", "e-health", "e-learning", "EdTech",
        "online curriculum", "virtual classroom", "chatbot", "IVR", "SMS-based",
    ],
    "enabling_processes": [
        "crowd-funding", "crowdsourcing", "crowd-sourced", "living lab", "innovation-challenge", "prize competition",
        "accelerator", "incubator", "venture fund", "co-design", "co-creation", "citizen science", "citizen-feedback",
        "social audit", "scorecard", "scorecards", "grievance-redress", "community-driven", "community-managed",
        "self-help group", "participatory-planning", "stakeholder platform", "multi-stakeholder", "knowledge-exchange",
        "South-South exchange", "cross-sector", "cross-sectoral", "cross-regional", "integrated approach",
        "systems approach",
    ],
    "public_good": [
        "climate-smart", "low-carbon", "nature-based", "circular economy", "gender-lens", "youth-led",
        "inclusive-innovation", "last-mile delivery", "social enterprise",
    ],
}

# Short, upper-case tokens must match as whole words and case-sensitively,
# otherwise "AI" hits "said" and "API" hits "capital". Everything else is
# matched case-insensitively with hyphen/space tolerance.
_CASE_SENSITIVE = {"AI", "API", "GIS", "IVR", "RCT", "PPP", "PforR", "M&E", "SMS-based", "EdTech"}


@dataclass(frozen=True)
class KeywordPattern:
    term: str
    dimension: str
    regex: re.Pattern


def _compile(term: str, dimension: str) -> KeywordPattern:
    parts = [re.escape(p) for p in re.split(r"[-\s]+", term) if p]
    body = r"[-\s]?".join(parts)
    flags = 0 if term in _CASE_SENSITIVE else re.IGNORECASE
    # plural / verbal suffix tolerance for multi-letter words
    return KeywordPattern(term, dimension, re.compile(rf"(?<![A-Za-z0-9&]){body}(?![A-Za-z0-9&])", flags))


PATTERNS: list[KeywordPattern] = [_compile(t, d) for d, terms in DIMENSIONS.items() for t in terms]
ALL_TERMS: list[str] = [p.term for p in PATTERNS]


@dataclass
class KeywordHit:
    term: str
    dimension: str
    count: int
    first_offset: int
    snippet: str

    def to_dict(self) -> dict:
        return {"term": self.term, "dimension": self.dimension, "count": self.count,
                "first_offset": self.first_offset, "snippet": self.snippet}


def scan(text: str, snippet_chars: int = 120) -> list[KeywordHit]:
    """Return one hit per *distinct* term found (count = occurrences)."""
    hits = []
    for p in PATTERNS:
        ms = list(p.regex.finditer(text))
        if not ms:
            continue
        m = ms[0]
        s, e = max(0, m.start() - snippet_chars), min(len(text), m.end() + snippet_chars)
        hits.append(KeywordHit(p.term, p.dimension, len(ms), m.start(), text[s:e].replace("\n", " ")))
    hits.sort(key=lambda h: -h.count)
    return hits


def tier(distinct_hits: int, high: int = 4, moderate: int = 2) -> str:
    if distinct_hits >= high:
        return "High"
    if distinct_hits >= moderate:
        return "Moderate"
    return "Low"
