"""Load and normalise ``projects.csv``.

The CSV is the single definition of which projects are in scope. Sector and
theme codes are stored as comma / semicolon separated strings with parallel
percentage lists; this module turns them into structured lists so that each
approach can later be matched to *one* sector and *one* theme.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

PROJECT_ID_RE = re.compile(r"^P\d{6}$")

# Sector names that themselves contain commas. They must be protected before
# the comma split, otherwise the names and the percentages fall out of step.
_PROTECTED_SECTOR_NAMES = [
    "Public Administration - Agriculture, Fishing, and Forestry",
    "Public Administration - Water, Sanitation, and Solid Waste Management",
    "Agricultural Markets, Commercialization, Agri-Business and Agriculture finance",
    "Other - Industry, Trade, and Services",
    "Other - Agriculture, Fishing, and Forestry",
    "FY17 - Agricultural markets, commercialization and agri-business",
    "FY17 - Public Administration - Industry, Trade and Services",
    "FY17 - Other Water Supply, Sanitation and Waste Management",
    "FY17 - Public Administration - Agriculture, Fishing and Forestry",
    "FY17 - Public Administration - Water, Sanitation and Waste Management",
    "FY17 - Research, and Other Support Activities",
]


@dataclass
class Share:
    """A sector or theme with its percentage share of the project."""

    name: str
    pct: float | None
    code_version: str = ""  # e.g. "FY17" when the name carried that prefix

    def to_dict(self) -> dict:
        return {"name": self.name, "pct": self.pct, "code_version": self.code_version}


@dataclass
class Project:
    project_id: str
    project_name: str
    country: str
    region: str
    vertical: str
    lead_practice: str
    status: str
    approval_date: str
    commitment_usd: float | None
    sectors: list[Share] = field(default_factory=list)
    themes: list[Share] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def fiscal_year(self) -> int | None:
        """World Bank fiscal year (July-June) of the approval date."""
        if not self.approval_date:
            return None
        try:
            y, m = int(self.approval_date[:4]), int(self.approval_date[5:7])
        except ValueError:
            return None
        return y + 1 if m >= 7 else y

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "country": self.country,
            "region": self.region,
            "vertical": self.vertical,
            "lead_practice": self.lead_practice,
            "status": self.status,
            "approval_date": self.approval_date,
            "approval_fy": self.fiscal_year,
            "commitment_usd": self.commitment_usd,
            "sectors": [s.to_dict() for s in self.sectors],
            "themes": [t.to_dict() for t in self.themes],
        }


def _strip_version(name: str) -> tuple[str, str]:
    m = re.match(r"^(FY\d{2})\s*-\s*(.*)$", name)
    return (m.group(2).strip(), m.group(1)) if m else (name.strip(), "")


def parse_sectors(names: str, percents: str) -> list[Share]:
    """Split ``sector_names`` / ``sector_percents`` into aligned shares."""
    pcts = [p.strip() for p in str(percents or "").split(",") if p.strip()]
    text = str(names or "")
    for i, p in enumerate(_PROTECTED_SECTOR_NAMES):
        text = text.replace(p, f"@@{i}@@")
    frags = [f.strip() for f in text.split(",") if f.strip()]
    frags = [re.sub(r"@@(\d+)@@", lambda m: _PROTECTED_SECTOR_NAMES[int(m.group(1))], f) for f in frags]
    has_fy = any(f.startswith("FY") for f in frags)
    # Residual mis-splits: glue lowercase / "and ..." fragments to the previous one.
    while len(frags) > len(pcts) and len(frags) > 1:
        idx = next(
            (i for i, f in enumerate(frags) if i > 0 and (f[:1].islower() or f.startswith("and ") or (has_fy and not f.startswith("FY")))),
            None,
        )
        if idx is None:
            break
        frags[idx - 1] += ", " + frags[idx]
        del frags[idx]
    shares = []
    for i, f in enumerate(frags):
        name, ver = _strip_version(f)
        pct = float(pcts[i]) if i < len(pcts) else None
        shares.append(Share(name=name, pct=pct, code_version=ver))
    shares.sort(key=lambda s: -(s.pct or 0))
    return shares


def parse_themes(themes: str) -> list[Share]:
    """Parse ``"A > B (30%); C > D (70%)"`` into shares (full path kept as name)."""
    out = []
    for item in re.split(r";\s*", str(themes or "")):
        item = item.strip()
        if not item:
            continue
        m = re.search(r"\((\d+(?:\.\d+)?)%\)\s*$", item)
        pct = float(m.group(1)) if m else None
        path = item[: m.start()].strip() if m else item
        parts = [p.strip() for p in path.split(">")]
        cleaned, ver = [], ""
        for p in parts:
            n, v = _strip_version(p)
            cleaned.append(n)
            ver = ver or v
        out.append(Share(name=" > ".join(cleaned), pct=pct, code_version=ver))
    out.sort(key=lambda s: -(s.pct or 0))
    return out


def _to_float(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def load_projects(csv_path: str | Path) -> dict[str, Project]:
    """Read ``projects.csv`` and return ``{project_id: Project}`` (first row wins on duplicates)."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    required = {"project_id", "project_name", "sector_names", "sector_percents", "themes"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"projects.csv is missing columns: {sorted(missing)}")
    projects: dict[str, Project] = {}
    for row in df.to_dict(orient="records"):
        pid = row["project_id"].strip()
        if not PROJECT_ID_RE.match(pid) or pid in projects:
            continue
        projects[pid] = Project(
            project_id=pid,
            project_name=row.get("project_name", ""),
            country=row.get("country", ""),
            region=row.get("region", ""),
            vertical=row.get("vertical", "") or "Unspecified",
            lead_practice=row.get("lead_practice", ""),
            status=row.get("status", ""),
            approval_date=row.get("approval_date", ""),
            commitment_usd=_to_float(row.get("commitment_usd")),
            sectors=parse_sectors(row.get("sector_names", ""), row.get("sector_percents", "")),
            themes=parse_themes(row.get("themes", "")),
            raw=row,
        )
    return projects


def validate_projects_csv(csv_path: str | Path) -> dict:
    """Quick validation report used by the web app's Setup page."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    ids = df["project_id"].str.strip()
    bad = sorted(i for i in ids if not PROJECT_ID_RE.match(i))
    dupes = sorted(ids[ids.duplicated()].unique().tolist())
    return {"rows": len(df), "unique_ids": ids.nunique(), "malformed_ids": bad, "duplicate_ids": dupes, "columns": list(df.columns)}
