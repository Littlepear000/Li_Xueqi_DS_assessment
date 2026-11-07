"""Crosswalks used by the analysis layer.

* ``major_sector``  - rolls the ~70 detailed sector codes (FY17 and newer) up to the
  11 World Bank major sectors, so that sector shares can be compared.
* ``theme_group``   - harmonises the two theme taxonomies found in ``projects.csv``
  (FY17 codes and the June-2025 taxonomy) into 11 comparable theme groups.
* ``region_group``  - short labels for the project regions.
* ``size_band`` / ``fy_period`` - bands for the extra analysis dimensions.

All mappings are rule based and deliberately transparent: every detailed value keeps
its original name in the mart, the rolled-up value sits next to it.
"""
from __future__ import annotations

# ----------------------------------------------------------------------------- sectors
MAJOR_SECTORS = [
    "Agriculture, Fishing & Forestry",
    "Education",
    "Energy & Extractives",
    "Financial Sector",
    "Health",
    "ICT / Digital",
    "Industry, Trade & Services",
    "Public Administration (cross-cutting)",
    "Social Protection",
    "Transportation",
    "Water, Sanitation & Waste",
]

# Ordered: the first rule that matches wins ("Public Administration - Agriculture ..." -> Agriculture).
_SECTOR_RULES: list[tuple[tuple[str, ...], str]] = [
    (("agri", "livestock", "irrigation", "fisher", "forestry", "crops"), "Agriculture, Fishing & Forestry"),
    (("information and communication", "ict infrastructure", "ict services", "digital"), "ICT / Digital"),
    (("educat",), "Education"),
    (("health",), "Health"),
    (("social protection", "social inclusion", "social cohesion"), "Social Protection"),
    (("energy", "renewable", "mining", "extractive"), "Energy & Extractives"),
    (("financial", "banking", "capital markets", "insurance", "non-bank"), "Financial Sector"),
    (("transport", "roads", "ports", "railways", "aviation"), "Transportation"),
    (("water", "sanitation", "waste"), "Water, Sanitation & Waste"),
    (("industry, trade", "tourism", "trade", "housing construction"), "Industry, Trade & Services"),
    (("central government", "sub-national government", "public administration"), "Public Administration (cross-cutting)"),
]


def major_sector(name: str) -> str:
    low = (name or "").lower()
    for keys, major in _SECTOR_RULES:
        if any(k in low for k in keys):
            return major
    return "Other / unmapped"


# ----------------------------------------------------------------------------- themes
THEME_GROUPS = [
    "Climate & Environment",
    "Digital & Data",
    "Economic Policy",
    "Finance",
    "Gender",
    "Governance & Public Sector",
    "Human Development",
    "Jobs & Private Sector",
    "Social Inclusion & FCV",
    "Urban, Rural & Resilience",
]


def theme_group(level1: str, level2: str) -> str:
    l1, l2 = (level1 or "").strip(), (level2 or "").strip()
    if l1 in ("Digital Transformation", "Data Ecosystem"):
        return "Digital & Data"
    if l1 == "Private Sector Development" and l2 == "ICT":
        return "Digital & Data"
    if l1 == "Public Sector Management" and l2.startswith("Data Development"):
        return "Digital & Data"
    if l1 in ("Environment and Natural Resource Management",
              "Environment, Infrastructure, and Natural Resource Management"):
        return "Climate & Environment"
    if l1 == "Gender" or (l1 == "Human Development and Gender" and l2 == "Gender"):
        return "Gender"
    if l1 in ("Human Development", "Human Development and Gender"):
        return "Human Development"
    if l1 == "Social Development and Protection" and l2 == "Social Protection":
        return "Human Development"
    if l1 in ("Private Sector Development", "Jobs"):
        return "Jobs & Private Sector"
    if l1 in ("Public Sector Management", "Governance and Public Sector Management"):
        return "Governance & Public Sector"
    if l1 == "Finance":
        return "Finance"
    if l1 == "Economic Policy":
        return "Economic Policy"
    if l1 in ("Social Development and Protection", "Social Sustainability",
              "Fragility, Conflict, and Violence", "Poverty and Equity"):
        return "Social Inclusion & FCV"
    if l1 in ("Urban and Rural Development", "Rural Development", "Disaster Risk Management",
              "Urban Development and Land Administration / Management"):
        return "Urban, Rural & Resilience"
    return "Other / unmapped"


# ----------------------------------------------------------------------------- regions
REGION_SHORT = {
    "Eastern and Southern Africa": "AFE - Eastern & Southern Africa",
    "Western and Central Africa": "AFW - Western & Central Africa",
    "Africa": "AFR - Africa (pre-FY21 code)",
    "East Asia and Pacific": "EAP - East Asia & Pacific",
    "Europe and Central Asia": "ECA - Europe & Central Asia",
    "Latin America and Caribbean": "LAC - Latin America & Caribbean",
    "Middle East, North Africa, Afghanistan, and Pakistan": "MENAAP - Middle East, N. Africa, Afg. & Pak.",
    "South Asia": "SAR - South Asia",
}


def region_group(region: str) -> str:
    return REGION_SHORT.get((region or "").strip(), "Other")


# ----------------------------------------------------------------------------- bands
def size_band(commitment_usd: float | None) -> str:
    if commitment_usd is None or commitment_usd != commitment_usd or commitment_usd <= 0:
        return "n/a"
    m = commitment_usd / 1e6
    if m < 50:
        return "1. < $50M"
    if m < 150:
        return "2. $50-150M"
    if m < 300:
        return "3. $150-300M"
    return "4. >= $300M"


def fy_period(fy: int | float | None) -> str:
    if fy is None or fy != fy:
        return "n/a"
    fy = int(fy)
    if fy <= 2021:
        return "FY19-21"
    if fy <= 2024:
        return "FY22-24"
    return "FY25-27"


# ----------------------------------------------------------------------------- technology archetypes (draft)
# Keyword rules on approach name + description. The D&AI pillars put ~85% of approaches in one
# pillar, so this second, technology-based lens is added for analysis. First match wins.
# DRAFT: rule based, to be replaced by an LLM-coded field once the definitions are agreed.
import re as _re

TECH_ARCHETYPES: list[tuple[str, str]] = [
    ("AI & advanced analytics", r"\bai\b|artificial intelligence|machine learning|predictive|big data|algorithm|chatbot|computer vision"),
    ("Geospatial & Earth observation", r"satellite|remote sensing|\bgis\b|geospatial|drone|\buav\b|lidar|mapping|cadastr|geo-?referenc"),
    ("Early warning & climate information", r"early warning|hydromet|forecast|weather|climate information|alert"),
    ("Digital ID, registries & DPI", r"digital id|identification|national id|registry|registries|interoperab|digital public infrastructure|\bdpi\b|data exchange|e-signature"),
    ("Digital payments & fintech", r"payment|mobile money|e-voucher|voucher|\bg2p\b|cashless|e-wallet|fintech|digital financial"),
    ("Startups & digital industry", r"startup|start-up|incubat|accelerat|venture|innovation fund|matching grant|tech park|entrepreneur"),
    ("Digital learning & skills", r"e-learning|elearning|online learning|digital skill|digital literacy|learning platform|edtech|online course|remote learning"),
    ("Connectivity & devices", r"broadband|connectivity|fiber|fibre|internet access|tablet|laptop|smartphone|\bdevices?\b"),
    ("E-services & e-government", r"portal|e-service|online|one-stop|single window|e-government|e-procurement|electronic|digital platform|web-based|e-health|telemedicine|telehealth"),
    ("Mobile & remote data collection", r"mobile|\bsms\b|\bivr\b|phone|kobo|\bodk\b|data collection|real-time|digital monitoring|grievance"),
    ("Information & management systems", r"information system|management system|\bmis\b|\bemis\b|\bhmis\b|database|dashboard|software|\berp\b|ifmis|data system|digital system|platform|digiti|digital"),
]
NON_DIGITAL = "No clear digital element"


def tech_archetype(text: str) -> str:
    t = (text or "").lower()
    for name, pattern in TECH_ARCHETYPES:
        if _re.search(pattern, t):
            return name
    return NON_DIGITAL
