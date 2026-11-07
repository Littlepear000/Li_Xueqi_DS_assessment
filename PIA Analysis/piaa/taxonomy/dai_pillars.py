"""Category taxonomy: the four pillars and ten solutions of the
*World Bank Group Digital & AI Implementation Plan (FY26-30)*.

An approach is assigned one **pillar** (its ``category``) and, where it fits,
one **solution** (its ``category_solution``). ``Digital Trust`` is the
cross-cutting layer of the plan (cybersecurity, data protection, responsible
AI); it is offered as a category for approaches that are primarily about trust
rather than about one pillar.

``cues`` are *hints* for the keyword pre-match and for the prompt; the final
assignment is made by the LLM match step and validated against the document.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Solution:
    id: str           # "S1" ... "S10"
    pillar: str       # pillar id
    title: str
    summary: str
    cues: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Pillar:
    id: str           # "P1" ... "P4", "PX" (cross-cutting)
    name: str
    goal: str


PILLARS: list[Pillar] = [
    Pillar("P1", "Access", "Connect people in hard-to-reach areas and improve usage of broadband internet"),
    Pillar("P2", "Affordability", "Make devices affordable, especially for the bottom 40% and MSMEs"),
    Pillar("P3", "Ecosystem", "Expand digitally enabled public and private services across sectors"),
    Pillar("P4", "AI Readiness and Adaptation", "Adopt, adapt and advance AI solutions, and leverage Small AI"),
    Pillar("PX", "Digital Trust (cross-cutting)", "Cybersecurity, data protection and responsible AI standards embedded across all solutions"),
]

SOLUTIONS: list[Solution] = [
    Solution("S1", "P1", "Eliminate persistent connectivity barriers",
             "Close first-, middle- and last-mile connectivity gaps (subsea cables, cross-border links, rural and remote "
             "coverage, bundled digital-energy infrastructure) by bundling policy advice, de-risking and standardized transactions.",
             ("broadband", "connectivity", "fiber", "fibre", "backbone", "subsea cable", "spectrum", "licensing", "rural connectivity",
              "last mile", "last-mile", "tower", "satellite", "infrastructure sharing", "rights-of-way", "mobile network", "4G", "5G")),
    Solution("S2", "P1", "Unlock private capital via a Digital Access Fund",
             "Pool MDB, DFI, philanthropic and private financing for hard-to-finance connectivity infrastructure.",
             ("digital access fund", "private capital", "blended finance", "guarantee", "de-risk", "co-financing", "investment fund")),
    Solution("S3", "P2", "Reduce upstream device costs",
             "Convene manufacturers on fit-for-purpose device specifications, advise on device tax and tariff reform, invest in manufacturing capacity.",
             ("device cost", "smartphone", "handset", "import tax", "tariff", "manufactur", "assembly", "OEM")),
    Solution("S4", "P2", "Expand device penetration",
             "De-risk consumer device financing (PayGo, BNPL, operator-anchored models) and targeted subsidies for low-income users and MSMEs.",
             ("device financing", "pay-as-you-go", "paygo", "buy-now-pay-later", "device subsidy", "smartphone", "handset", "2G", "4G migration")),
    Solution("S5", "P2", "Increase the supply of high-quality devices",
             "Formalize refurbishing, enable cross-border movement of used devices, invest in quality-assured refurbishers.",
             ("refurbish", "used device", "second-hand", "trade-in", "e-waste")),
    Solution("S6", "P3", "Scale and enhance digital service delivery",
             "Digital Public Infrastructure (digital ID, e-signature, digital payments, data sharing, base registries, verifiable credentials), "
             "integrated and life-event based service delivery, AI and emerging technologies in service delivery, assisted delivery channels.",
             ("digital public infrastructure", "DPI", "digital ID", "national ID", "identification", "e-signature", "digital payment",
              "G2P", "interoperab", "registry", "registries", "data exchange", "data sharing", "e-government", "e-service", "one-stop",
              "digital platform", "information system", "MIS", "management information system", "portal", "mobile application", "app",
              "electronic", "digitiz", "digitis", "digital service", "e-health", "telemedicine", "e-learning", "EdTech", "e-procurement",
              "GIS", "geospatial", "remote sensing", "satellite imagery", "drone", "digital twin", "early warning", "SMS", "IVR", "call center",
              "kiosk", "community center")),
    Solution("S7", "P3", "Catalyze local digital industries",
             "Government outsourcing to local digital firms, tech parks and zones, innovation funds, matching grants, venture financing and exit mechanisms.",
             ("startup", "start-up", "incubat", "accelerat", "venture", "matching grant", "innovation fund", "tech park", "technopark",
              "digital industry", "IT sector", "BPO", "outsourc", "digital entrepreneur", "innovation hub", "challenge fund")),
    Solution("S8", "P3", "Boost and diffuse digital skills",
             "Digital literacy, sector-specific and job-relevant digital skills, advanced skills, through technical assistance, peer learning and public-private delivery.",
             ("digital skills", "digital literacy", "ICT skills", "coding", "upskill", "reskill", "training", "e-learning platform", "online course",
              "digital training", "computer lab", "STEM")),
    Solution("S9", "P4", "Enable locally relevant Small AI solutions",
             "Replicate proven Small AI use cases (predictive, generative, agentic; low-resource, edge and offline), AI academies for government, "
             "edge compute for rural communities; sectoral deployments in agriculture, health, education, crisis response.",
             ("artificial intelligence", "AI", "machine learning", "ML", "predictive", "generative", "chatbot", "large language model", "LLM",
              "algorithm", "automated", "image recognition", "computer vision", "natural language", "decision support", "advisory tool",
              "AI-enabled", "AI-based", "smart", "precision agriculture", "yield prediction", "forecast")),
    Solution("S10", "P4", "Strengthen AI infrastructure",
             "Fit-for-purpose compute capacity, data centers and AI-ready data systems; governance, de-risking private investment.",
             ("data center", "data centre", "cloud", "compute", "GPU", "high-performance computing", "AI-ready data", "data governance",
              "open data", "data infrastructure", "data lake", "data warehouse")),
    Solution("SX", "PX", "Digital trust, safety and security",
             "Cybersecurity, data protection and privacy, responsible and safe AI governance.",
             ("cybersecurity", "cyber security", "data protection", "privacy", "responsible AI", "AI governance", "digital safety",
              "security operations", "CERT")),
]

PILLAR_BY_ID = {p.id: p for p in PILLARS}
SOLUTION_BY_ID = {s.id: s for s in SOLUTIONS}


NO_SOLUTION_CODES = ("", "NONE", "NO", "N/A")


def resolve_solution(code: str) -> Solution | None:
    """Normalise a model/reviewer answer ("S6", "s6", "Solution 6", a title) to a Solution, or None."""
    v = (code or "").strip()
    if v.upper() in NO_SOLUTION_CODES:
        return None
    key = v.upper().replace("SOLUTION", "").replace(" ", "")
    if key in SOLUTION_BY_ID:
        return SOLUTION_BY_ID[key]
    low = v.lower()
    for sol in SOLUTIONS:
        if sol.title.lower() == low:
            return sol
    return None


def pillar_attributes(solution: Solution | None) -> tuple[str, str]:
    """(pillar name, pillar id) for a solution. The pillar is always derived from the solution:
    the Implementation Plan maps every solution to exactly one pillar."""
    if solution is None:
        return "none", "NONE"
    pillar = PILLAR_BY_ID[solution.pillar]
    return pillar.name, pillar.id


def solutions_for_pillar(pillar_id: str) -> list[Solution]:
    return [s for s in SOLUTIONS if s.pillar == pillar_id]


def taxonomy_text() -> str:
    """Compact description used inside prompts."""
    lines = []
    for p in PILLARS:
        lines.append(f"{p.id} {p.name}: {p.goal}")
        for s in solutions_for_pillar(p.id):
            lines.append(f"   {s.id} {s.title} - {s.summary}")
    return "\n".join(lines)


def cue_hits(text: str) -> dict[str, int]:
    """Count cue occurrences per solution (cheap, case-insensitive). Used only as a hint."""
    low = text.lower()
    out = {}
    for s in SOLUTIONS:
        n = 0
        for c in s.cues:
            if len(c) <= 3 or c.isupper():  # AI, ML, MIS, GIS, DPI, SMS, IVR, LLM, GPU, OEM, BPO, STEM, CERT, G2P, 2G/4G/5G
                n += text.count(c)
            else:
                n += low.count(c.lower())
        if n:
            out[s.id] = n
    return out
