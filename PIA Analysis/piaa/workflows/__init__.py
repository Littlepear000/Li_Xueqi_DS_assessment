"""Workflow registry.

A workflow version is a folder under ``piaa/workflows/`` containing::

    workflow.html   human-readable description shown in the web app
    config.yaml     parameters (document rules, thresholds, model, step list)
    prompts/*.md    prompt templates with {{placeholders}}
    steps.py        a ``run(ctx)`` function that executes the steps
    CHANGELOG.md    what changed between versions

    releases.json   released states of the folder -> version tags (v1.0, v1.1 ...)

The folder is hashed so that every result records exactly which code and
prompts produced it; the hash is mapped to a version tag through
``releases.json`` (see :mod:`piaa.versioning`).
"""
from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

WORKFLOWS_ROOT = Path(__file__).parent


@dataclass
class Workflow:
    version: str
    path: Path
    config: dict
    prompts: dict[str, str] = field(default_factory=dict)
    hash: str = ""

    @property
    def name(self) -> str:
        return self.config.get("name", self.version)

    @property
    def description_html(self) -> str:
        p = self.path / "workflow.html"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def prompt(self, key: str, **values) -> str:
        """Fill ``{{key}}`` placeholders in a prompt template."""
        text = self.prompts[key]
        for k, v in values.items():
            text = text.replace("{{" + k + "}}", str(v))
        return text

    def module(self):
        return importlib.import_module(f"piaa.workflows.{self.version}.steps")

    @property
    def releases(self) -> list[dict]:
        from ..versioning import load_releases
        return load_releases(self.path)

    @property
    def tag(self) -> str:
        """Version tag of the folder as it is now (``v1.1``, or ``v1.1+dev`` after unreleased edits)."""
        from ..versioning import current_tag
        return current_tag(self.version, self.hash, self.releases)

    @property
    def released(self) -> bool:
        return not self.tag.endswith("+dev")

    def to_dict(self) -> dict:
        return {"version": self.version, "name": self.name, "hash": self.hash, "tag": self.tag, "released": self.released,
                "releases": self.releases, "steps": self.config.get("steps", []), "config": self.config}


HASH_EXCLUDE = {"CHANGELOG.md"}   # documentation only; editing it must not change the version


def _hash_folder(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if (p.is_file() and p.suffix in {".py", ".md", ".yaml", ".yml", ".html"} and "__pycache__" not in p.parts
                and p.name not in HASH_EXCLUDE):
            h.update(p.relative_to(path).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def load_workflow(version: str) -> Workflow:
    path = WORKFLOWS_ROOT / version
    cfg_path = path / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"workflow '{version}' not found under {WORKFLOWS_ROOT}")
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    prompts = {p.stem: p.read_text(encoding="utf-8") for p in sorted((path / "prompts").glob("*.md"))}
    return Workflow(version=version, path=path, config=config, prompts=prompts, hash=_hash_folder(path))


def list_workflows() -> list[Workflow]:
    out = []
    for p in sorted(WORKFLOWS_ROOT.iterdir()):
        if p.is_dir() and (p / "config.yaml").exists():
            out.append(load_workflow(p.name))
    return out
