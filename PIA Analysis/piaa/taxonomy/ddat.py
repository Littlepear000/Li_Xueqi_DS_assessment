"""Digital & Data Approach Taxonomy (DDAT) and its mapping to the Digital & AI
Implementation Plan solutions.

Sources (bundled verbatim under ``piaa/reference/``, built from
*The World Bank Theme Taxonomy: June 2025* and the *Digital & AI
Implementation Plan FY26-30*):

* ``ddat_themes.json``       - the 21 approaches (13 under 250000 Digital
                               Transformation, 8 under 270000 Data Ecosystem)
                               with definitions, typical examples and third-level themes
* ``ddat_exclusions.json``   - 192 excluded activities with "see instead" pointers
* ``dai_solutions.json``     - pillars P1-P4 and solutions S1-S10 (+ TRUST)
* ``ddat_solution_map.json`` - approach -> candidate solutions and the "assign when" rules

This module exposes them as plain objects, builds the keyword lists used for
candidate matching (Methodology Note 1, step 2) and renders the taxonomy text
that is placed - once, cached - in the classification system prompt.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "reference"


@dataclass
class ThirdLevel:
    code: str
    name: str
    definition: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class DdatApproach:
    code: str
    name: str
    parent_code: str
    parent_name: str
    definition: str
    examples: list[str]
    third_level: list[ThirdLevel]
    exclusions: list[dict] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.code} {self.name}"


# ----------------------------------------------------------------------------
# Curated keyword seeds per approach (English + common French / Spanish /
# Portuguese equivalents). Third-level theme names are added automatically.
# Matching is case-insensitive, hyphen/space tolerant; short upper-case tokens
# (AI, IoT, GIS ...) match as whole words, case-sensitively.
# ----------------------------------------------------------------------------
KEYWORD_SEEDS: dict[str, list[str]] = {
    "250100": ["broadband", "connectivity", "internet access", "fiber", "fibre", "fibre optique", "fibra", "backbone", "spectrum",
               "telecom", "telecommunication", "télécommunication", "telecomunicaciones", "mobile network", "4G", "5G", "last mile",
               "last-mile", "rural connectivity", "universal access", "universal service", "ICT regulator", "tower", "satellite internet",
               "submarine cable", "haut débit", "banda ancha", "banda larga", "device subsidy", "smartphone", "voucher"],
    "250200": ["data center", "data centre", "centre de données", "centro de datos", "cloud", "nuage", "nube", "nuvem", "hosting",
               "server", "servers", "computing infrastructure", "government cloud", "storage infrastructure", "colocation"],
    "250300": ["artificial intelligence", "intelligence artificielle", "inteligencia artificial", "inteligência artificial", "AI",
               "machine learning", "apprentissage automatique", "aprendizaje automático", "deep learning", "neural network", "algorithm",
               "predictive", "predictive analytics", "chatbot", "large language model", "LLM", "generative", "computer vision",
               "natural language", "IoT", "internet of things", "blockchain", "distributed ledger", "quantum", "drone", "robot",
               "automation", "automated", "smart sensor", "sensor network", "digital twin", "emerging technolog"],
    "250400": ["cybersecurity", "cyber security", "cyber-security", "cybersécurité", "ciberseguridad", "cibersegurança", "cyber",
               "CERT", "CSIRT", "security operations", "incident response", "critical information infrastructure", "cyber resilience",
               "information security", "encryption"],
    "250500": ["data protection", "protection des données", "protección de datos", "proteção de dados", "privacy", "privacité",
               "privacidad", "privacidade", "personal data", "données personnelles", "datos personales", "GDPR", "data protection authority",
               "consent", "anonymi"],
    "250600": ["digital ID", "digital identity", "identité numérique", "identidad digital", "identidade digital", "national ID",
               "identification system", "civil registration", "état civil", "registro civil", "birth registration", "e-signature",
               "electronic signature", "signature électronique", "firma electrónica", "trust services", "interoperab", "data exchange",
               "data sharing platform", "X-Road", "government service bus", "digital public infrastructure", "DPI", "digital payment",
               "government-to-person", "G2P", "social registry", "unique identifier", "beneficiary registry"],
    "250700": ["e-government", "e-governance", "digital government", "gouvernement numérique", "gobierno digital", "governo digital",
               "e-service", "online service", "digital public service", "one-stop", "portal", "government portal", "GovTech", "govtech",
               "digital transformation of", "digitalization of", "digitalisation of", "digitization of", "digitisation of", "e-procurement",
               "electronic procurement", "e-GP", "digital service delivery", "citizen-centric", "user-centric", "service delivery platform",
               "chief digital officer", "digital agency", "whole-of-government", "enterprise architecture", "government training",
               "management information system", "MIS", "HRMIS", "IFMIS", "e-office", "digital platform"],
    "250800": ["digital economy", "économie numérique", "economía digital", "economia digital", "ICT industry", "ICT sector", "tech park",
               "technology park", "technopark", "startup", "start-up", "incubator", "accelerator", "venture", "innovation hub", "BPO",
               "IT-enabled services", "ITES", "outsourcing", "e-commerce", "digital market", "data economy", "data market", "smart industry",
               "industry 4.0", "digital entrepreneur", "digital business", "fintech", "digital financial services", "mobile money"],
    "250900": ["green digital", "e-waste", "energy-efficient data", "digital for climate", "smart grid", "smart meter", "climate information system",
               "environmental monitoring system", "digital monitoring of emissions", "carbon footprint of ICT", "sustainable ICT"],
    "251000": ["digital inclusion", "inclusion numérique", "inclusión digital", "inclusão digital", "digital divide", "fracture numérique",
               "brecha digital", "gender digital", "women's access to digital", "persons with disabilities", "accessibility", "assistive technolog",
               "online safety", "online harassment", "child online", "underserved communities", "marginalized groups digital"],
    "251100": ["fragile", "conflict", "displaced", "refugee", "réfugié", "refugiado", "host communities", "humanitarian", "FCV", "FCS",
               "IDP", "internally displaced", "crisis response digital", "early warning"],
    "251200": ["digital skills", "compétences numériques", "habilidades digitales", "competências digitais", "digital literacy",
               "alphabétisation numérique", "alfabetización digital", "coding", "programming", "ICT skills", "ICT training", "digital jobs",
               "online work", "gig", "freelanc", "tech talent", "STEM", "computer literacy", "e-learning", "online learning", "EdTech",
               "digital training", "bootcamp", "upskill", "reskill", "software engineer"],
    "251300": ["digital agriculture", "agriculture numérique", "agricultura digital", "e-agriculture", "precision agriculture",
               "precision farming", "farmer advisory", "e-extension", "digital extension", "agri-tech", "agritech", "AgTech", "e-voucher",
               "e-health", "ehealth", "telemedicine", "télémédecine", "telemedicina", "telehealth", "health information system", "HMIS", "DHIS",
               "electronic medical record", "e-learning platform", "digital learning", "learning management system", "smart city",
               "intelligent transport", "e-ticketing", "digital logistics", "mobile application", "mobile app", "SMS", "USSD", "digital tool",
               "digital solution", "digital system", "digital technolog", "ICT solution", "online platform", "digital platform",
               "early warning system", "weather information", "market information system", "traceability", "e-registration"],
    "270100": ["data standard", "metadata standard", "statistical standard", "classification standard", "SDMX", "methodolog", "survey methodology",
               "sampling frame", "data quality framework", "common data model", "data dictionary", "statistical methods"],
    "270200": ["data collection", "collecte de données", "recolección de datos", "coleta de dados", "survey", "enquête", "encuesta",
               "census", "recensement", "censo", "household survey", "agricultural census", "administrative data", "sensor data", "mobile phone data",
               "citizen-generated data", "big data", "web scraping", "CAPI", "computer-assisted", "enumerator", "tablet-based data",
               "digital data collection", "satellite data"],
    "270300": ["data management", "gestion des données", "gestión de datos", "data quality", "data cleaning", "data curation", "data archiv",
               "data preservation", "data documentation", "data repository", "master data", "data integration", "data warehouse", "data lake",
               "data catalogue", "data catalog", "interoperability of data"],
    "270400": ["data dissemination", "open data", "données ouvertes", "datos abiertos", "dados abertos", "data portal", "statistical portal",
               "dashboard", "tableau de bord", "information system", "MIS", "data platform", "data visualization", "data visualisation",
               "data-driven tool", "data application", "API", "open access to data", "microdata", "data release", "statistical website", "publication of data"],
    "270500": ["data use", "data-driven decision", "evidence-based decision", "data for decision", "use of data", "utilisation des données",
               "uso de datos", "data analytics", "analytics", "data analysis", "data insight", "monitoring data", "data demand", "data literacy of users",
               "data journalism", "performance data"],
    "270600": ["data policy", "data governance", "gouvernance des données", "gobernanza de datos", "governança de dados", "data strategy",
               "statistical law", "statistics act", "statistical legislation", "data law", "data regulation", "data assessment", "data diagnostic",
               "data rights", "data stewardship", "national statistical system", "statistical strategy", "NSDS", "open data policy", "data sharing agreement"],
    "270700": ["statistical capacity", "capacité statistique", "capacidad estadística", "capacidade estatística", "data literacy",
               "statistical training", "national statistics office", "NSO", "statistical institute", "statistics bureau", "INS", "INE", "IBGE",
               "data institution", "data ethics", "training on data", "capacity building on data", "statistical capacity building", "data skills"],
    "270800": ["geospatial", "géospatial", "geoespacial", "GIS", "geographic information system", "remote sensing", "télédétection",
               "teledetección", "earth observation", "satellite imagery", "imagerie satellitaire", "imágenes satelitales", "spatial data",
               "cadastre", "cadastral", "land information system", "mapping", "digital map", "LIDAR", "drone imagery", "geo-referenced",
               "georeferenced", "geocod", "spatial data infrastructure", "NSDI", "GPS", "GNSS", "location data", "aerial imagery"],
}

_CASE_SENSITIVE = {"AI", "IoT", "LLM", "GIS", "GPS", "MIS", "API", "DPI", "G2P", "SMS", "USSD", "CERT", "CSIRT", "FCV", "FCS", "IDP",
                   "BPO", "ITES", "NSO", "INS", "INE", "IBGE", "HMIS", "DHIS", "HRMIS", "IFMIS", "STEM", "SDMX", "CAPI", "NSDS", "NSDI",
                   "GNSS", "4G", "5G", "GDPR", "LIDAR", "AgTech", "EdTech", "GovTech", "X-Road"}


@dataclass(frozen=True)
class KeywordPattern:
    term: str
    code: str
    regex: re.Pattern


def _compile(term: str, code: str) -> KeywordPattern:
    parts = [re.escape(p) for p in re.split(r"[-\s]+", term) if p]
    body = r"[-\s]?".join(parts)
    flags = 0 if term in _CASE_SENSITIVE else re.IGNORECASE
    # prefix match for stems ending in a letter (digitalization/digitalisation, interoperab-ility ...)
    tail = r"(?![A-Za-z0-9&])" if (term in _CASE_SENSITIVE or len(parts[-1]) < 5) else r"[a-z]*(?![A-Za-z0-9&])"
    return KeywordPattern(term, code, re.compile(rf"(?<![A-Za-z0-9&]){body}{tail}", flags))


# ----------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load() -> dict:
    themes = json.loads((REF / "ddat_themes.json").read_text(encoding="utf-8"))
    excl = json.loads((REF / "ddat_exclusions.json").read_text(encoding="utf-8"))
    sols = json.loads((REF / "dai_solutions.json").read_text(encoding="utf-8"))
    smap = json.loads((REF / "ddat_solution_map.json").read_text(encoding="utf-8"))
    ex_by_code: dict[str, list[dict]] = {}
    for e in excl["exclusions"]:
        ex_by_code.setdefault(e["approach_code"], []).append(e)
    approaches: dict[str, DdatApproach] = {}
    for a in themes["approaches"]:
        tl = [ThirdLevel(t["code"], t["name"], t.get("definition", ""), [x["text"] for x in t.get("typical_examples", [])])
              for t in a.get("third_level_themes", [])]
        kws = list(KEYWORD_SEEDS.get(a["approach_code"], [])) + [t.name for t in tl]
        approaches[a["approach_code"]] = DdatApproach(
            a["approach_code"], a["approach_name"], a["parent_theme_code"], a["parent_theme_name"], a["definition"],
            [x["text"] for x in a["typical_examples"]], tl, ex_by_code.get(a["approach_code"], []), kws)
    solutions = {}
    pillar_of = {}
    for p in sols["pillars"]:
        for s in p["solutions"]:
            solutions[s["solution_code"]] = {**s, "pillar_code": p["pillar_code"], "pillar_name": p["pillar_name"]}
            pillar_of[s["solution_code"]] = (p["pillar_code"], p["pillar_name"])
    cc = sols["cross_cutting"]
    solutions["TRUST"] = {"solution_code": "TRUST", "title": cc["name"], "description": cc["description"], "pillar_code": "", "pillar_name": ""}
    pillar_of["TRUST"] = ("", "")
    mapping = {m["approach_code"]: m for m in smap["mapping"]}
    return {"approaches": approaches, "solutions": solutions, "pillar_of": pillar_of, "mapping": mapping,
            "assign_when": smap["assign_when"], "pillars": {p["pillar_code"]: p for p in sols["pillars"]},
            "versions": {"ddat": themes.get("version"), "dai": sols.get("version"), "map": smap.get("version")}}


def approaches() -> dict[str, DdatApproach]:
    return load()["approaches"]


@lru_cache(maxsize=1)
def patterns() -> list[KeywordPattern]:
    out = []
    for a in approaches().values():
        for t in a.keywords:
            out.append(_compile(t, a.code))
    return out


def keyword_hits(sentence: str) -> dict[str, list[str]]:
    """{approach_code: [terms]} for the terms found in one sentence."""
    hits: dict[str, list[str]] = {}
    for p in patterns():
        if p.regex.search(sentence):
            hits.setdefault(p.code, []).append(p.term)
    return hits


def theme_text(code: str) -> str:
    """Definition + examples + third-level names: the text used for semantic matching."""
    a = approaches()[code]
    parts = [a.name, a.definition, *a.examples]
    for t in a.third_level:
        parts += [t.name, t.definition, *t.examples[:3]]
    return " ".join(parts)


def taxonomy_prompt_text(include_exclusions: bool = True) -> str:
    """The DDAT entries as they are placed (cached) in the classification system prompt."""
    lines = ["DIGITAL & DATA APPROACH TAXONOMY (DDAT) - 21 approaches. Judge matches against these entries only.", ""]
    for a in approaches().values():
        lines.append(f"=== {a.code} {a.name} (parent {a.parent_code} {a.parent_name}) ===")
        lines.append("Definition: " + a.definition)
        lines.append("Typical examples of coded activities:")
        lines += [f"  - {e}" for e in a.examples]
        if a.third_level:
            lines.append("Third-level themes:")
            for t in a.third_level:
                lines.append(f"  - {t.code} {t.name}: {t.definition[:400]}")
        if include_exclusions and a.exclusions:
            lines.append("Examples of EXCLUDED activities (do not code here" + "; 'see' = code there instead if it fits):")
            for e in a.exclusions:
                see = f" [see {', '.join(e['see_instead'])}]" if e.get("see_instead") else ""
                lines.append(f"  - {e['text']}{see}")
        lines.append("")
    return "\n".join(lines)


def solution_candidates(code: str) -> tuple[list[str], str]:
    m = load()["mapping"].get(code)
    if not m:
        return [], "none"
    return list(m["candidate_solutions"]), m["rule"]


def solution_prompt_text(codes: list[str]) -> str:
    d = load()
    out = []
    for c in codes:
        s = d["solutions"][c]
        out.append(f"{c} ({s['pillar_code'] or 'cross-cutting'} {s['pillar_name'] or 'Trust'}): {s['title']}\n  Assign here when: {d['assign_when'].get(c, '')}\n  Plan text: {s['description'][:900]}")
    return "\n\n".join(out)


def pillar_for(solution_code: str) -> tuple[str, str]:
    return load()["pillar_of"].get(solution_code, ("", ""))


def solution_title(solution_code: str) -> str:
    s = load()["solutions"].get(solution_code)
    return s["title"] if s else solution_code
