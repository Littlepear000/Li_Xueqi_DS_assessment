"""Innovation categories used from workflow v4 on.

Source: Table 3.4 and Section 3 of *Innovation Patterns in the World Bank
Group Portfolio* (working paper in ``background/``). The paper groups the
innovations found in the lending portfolio into four families. Workflow v4
uses them as the **category** of an approach, with one extra precondition set
by the review team: the approach must be related to digital technology, data
or AI.
"""
from __future__ import annotations

CATEGORIES: dict[str, dict] = {
    "Operational": {
        "full_name": "Operational / Institutional",
        "definition": (
            "Innovations that re-engineer delivery arrangements to improve the quality, effectiveness and/or efficiency of "
            "development solutions: new ways of designing or implementing projects that go beyond incremental improvements, "
            "new delivery systems, transparency and accountability mechanisms, institutional set-ups that require systems change."),
        "examples": ["e-governance and e-procurement", "public-private partnerships (PPPs)", "pilot tranches that test feasibility before scale-up",
                     "real-time beneficiary feedback (citizen scorecards, SMS-based progress updates)", "flexible designs allowing course-correction",
                     "digital grievance or case-management systems that change how services are delivered"],
        "contexts": "All sectors, especially complex or fragile environments",
    },
    "Technological": {
        "full_name": "Technological",
        "definition": (
            "Innovations centred on the development or adaptation of new technologies to solve development challenges - often "
            "general-use technologies adopted and adapted to improve efficiency in new sectors or geographies (faster processing, "
            "remote service delivery, richer data collection)."),
        "examples": ["digital services such as telemedicine or e-learning", "remote sensing and satellite monitoring", "AI / machine-learning tools",
                     "mobile applications and SMS/USSD services", "management information systems and digital registries", "IoT sensors, drones, GIS"],
        "contexts": "Middle-income geographies; urban, governance and health sectors; success depends on connectivity, training and user ownership",
    },
    "Financial": {
        "full_name": "Financial",
        "definition": (
            "Innovations that create or disseminate new financial products, services, technologies or processes that improve or "
            "transform financial transactions and services - efficiency, accessibility, affordability and functionality of financial "
            "markets and services, particularly for underserved populations; instruments that de-risk projects by linking funding to results."),
        "examples": ["digital payment systems and mobile banking / mobile money", "fintech and digital credit scoring (e.g. psychometric testing)",
                     "output-based or results-based disbursement delivered through digital verification", "community funds and digital grant windows",
                     "e-vouchers and digital subsidies", "partial credit guarantees supported by digital platforms"],
        "contexts": "Financial inclusion, service delivery, urban or rural; needs strong governance and aligned incentives",
    },
    "Collaborative": {
        "full_name": "Collaborative",
        "definition": (
            "Innovations that bring together diverse actors - governments, private sector, civil society, academia, communities - to "
            "jointly address development challenges: self-help groups, multi-stakeholder coalitions, social entrepreneurship, "
            "community-driven solutions, with digital tools as the enabler of the collaboration."),
        "examples": ["digital platforms for multi-stakeholder coordination or data sharing between agencies", "crowdsourcing and citizen reporting apps",
                     "community-driven development supported by digital monitoring", "open-data or hackathon / innovation-challenge partnerships",
                     "public-private digital service delivery partnerships", "peer learning and knowledge-exchange platforms"],
        "contexts": "Fragile, rural and natural-resource projects; uptake depends on trust-building and clear partner roles",
    },
}

DIGITAL_RULE = (
    "An approach qualifies ONLY if it is related to digital technology, data or artificial intelligence: the innovation is delivered "
    "through, enabled by, or consists of digital systems, data, connectivity, software, mobile or online channels, automation, AI/ML, "
    "remote sensing or similar. A purely non-digital innovation (a new tariff policy, a community meeting format, a cash grant with "
    "no digital element) is NOT an approach for this analysis, even if it fits a category.")

ADOPTION_RULE = (
    "adoption describes what the sentence (read with its context) says the project does with the approach:\n"
    "- apply    : THIS project finances, procures, builds, deploys, pilots, scales, requires or has implemented it "
    "(component or sub-component activity, cost line, results indicator / DLI, covenant or prior action, implementation progress).\n"
    "- prospect : the approach is envisaged for the future - a later phase, a follow-on operation, 'will be considered', 'may explore', "
    "a government vision or strategy, expected benefits - but this project does not commit to it.\n"
    "- discuss  : the approach is discussed - advantages, disadvantages, risks, lessons from elsewhere, other programmes, options weighed, "
    "background - without this project adopting it.")


def prompt_text() -> str:
    lines = ["INNOVATION CATEGORIES (working paper 'Innovation Patterns in the World Bank Group Portfolio', Table 3.4)", ""]
    for key, c in CATEGORIES.items():
        lines.append(f"=== {key} ({c['full_name']}) ===")
        lines.append("Definition: " + c["definition"])
        lines.append("Examples: " + "; ".join(c["examples"]))
        lines.append("Typical contexts: " + c["contexts"])
        lines.append("")
    lines.append("DIGITAL / AI PRECONDITION")
    lines.append(DIGITAL_RULE)
    lines.append("")
    lines.append("ADOPTION")
    lines.append(ADOPTION_RULE)
    return "\n".join(lines)
