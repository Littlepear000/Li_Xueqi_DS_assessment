"""Smoke test: run workflow v1 with the mock LLM on a tiny synthetic corpus."""
from pathlib import Path

import pytest

from piaa.catalog import parse_sectors, parse_themes
from piaa.config import LLMSettings, Settings
from piaa.documents import build_index, locate_span, verify_span
from piaa.export import export
from piaa.runner import run_batch, run_project
from piaa.taxonomy import innovation_keywords as ik

CSV = """project_id,project_name,country,region,vertical,lead_practice,status,approval_date,commitment_usd,sector_names,sector_percents,themes
P100001,Digital Farmers Project,Benin,Western and Central Africa,Planet,Farming and Agribusiness,Active,2021-03-01,"50,000,000","FY17 - Agricultural Extension, Research, and Other Support Activities,FY17 - ICT Services","70.0,30.0",FY17 - Private Sector Development > FY17 - ICT (60%); FY17 - Human Development and Gender > FY17 - Gender (40%)
P100002,Rural Roads,Benin,Western and Central Africa,Infrastructure,Transport and Logistics,Closed,2019-05-01,"20,000,000",FY17 - Rural and Inter-Urban Roads,100.0,FY17 - Urban and Rural Development > FY17 - Rural Development (100%)
"""
DOC1 = ("Project Appraisal Document. The project will pilot a digital advisory platform that sends SMS-based weather alerts to farmers. "
        "Building on the experience of P100002, the project will scale up a mobile money payment system for input subsidies. "
        "An innovative machine-learning model will forecast pest outbreaks using satellite imagery. Component 3 finances rural roads. ")
DOC2 = "Project Appraisal Document. The project rehabilitates 300 km of rural roads. Routine maintenance contracts are financed. "


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    (tmp_path / "projects.csv").write_text(CSV, encoding="utf-8")
    d = tmp_path / "documents"; d.mkdir()
    (d / "P100001_PAD_2021-02-01_111.txt").write_text(DOC1, encoding="utf-8")
    (d / "P100002_PAD_2019-04-01_222.txt").write_text(DOC2, encoding="utf-8")
    return tmp_path


def test_parsing():
    s = parse_sectors("FY17 - Agricultural Extension, Research, and Other Support Activities,FY17 - ICT Services", "70.0,30.0")
    assert [x.name for x in s] == ["Agricultural Extension, Research, and Other Support Activities", "ICT Services"]
    t = parse_themes("FY17 - Private Sector Development > FY17 - ICT (60%); FY17 - Human Development and Gender > FY17 - Gender (40%)")
    assert t[0].name == "Private Sector Development > ICT" and t[0].pct == 60


def test_keywords():
    hits = {h.term for h in ik.scan(DOC1)}
    assert {"pilot", "scale-up", "mobile money", "innovative", "satellite imagery", "machine-learning", "SMS-based"} <= hits
    assert "AI" not in {h.term for h in ik.scan("the chairman said hello")}


def test_locate_and_verify(raw):
    idx = build_index([raw / "documents"])
    doc = idx.for_project("P100001")[0]
    span = locate_span(doc, "An innovative machine learning model will forecast pest outbreaks using satellite imagery.")
    assert span and span.match_kind == "fuzzy" and "machine-learning" in span.text
    assert verify_span(doc, span)


def test_pipeline_mock(raw, tmp_path):
    s = Settings(raw_dir=raw, output_dir=tmp_path / "out", llm=LLMSettings(provider="mock"))
    rec = run_project("P100001", s)
    assert rec.error == "" and rec.innovation_tier == "High" and rec.innovative == "Yes"
    assert rec.approaches and all(a.evidence.text in DOC1 for a in rec.approaches)
    assert rec.approaches[0].category.code == "P3" and rec.approaches[0].sector.value.startswith("Agricultural Extension")
    assert any(l.other_project_id == "P100002" and l.kind == "explicit_reference" for l in rec.approaches[0].replication)
    recs = run_batch(None, s, mode="reuse")
    assert recs["P100001"].run_id == rec.run_id  # reused from cache
    assert recs["P100002"].innovative == "No" and recs["P100002"].innovation_tier == "Low"
    from piaa.catalog import load_projects
    m = export(recs, load_projects(s.projects_csv), s.output_dir, "test")
    assert m["projects"] == 2 and Path(m["files"]["xlsx"]).exists()
    import pandas as pd
    x = pd.ExcelFile(m["files"]["xlsx"])
    assert x.sheet_names[0] == "project_approaches" and "projects" in x.sheet_names and "data_dictionary" in x.sheet_names
