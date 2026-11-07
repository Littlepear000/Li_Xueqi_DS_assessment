"""Version tags for workflows and for every result the package writes.

Three levels of version information are recorded:

``package_version``
    ``piaa.__version__`` (also in ``pyproject.toml``). Bumped when shared code
    outside the workflow folders changes in a way that affects results.

``workflow`` (folder) + ``workflow_tag``
    A workflow folder (``piaa/workflows/v1``, ``piaa/patterns/r2`` ...) is a
    *major* version. Inside a folder, every released state gets a tag
    ``<folder>.<n>`` (``v1.0``, ``v1.1``, ``r2.0`` ...). Releases are listed in
    the folder's ``releases.json``::

        [{"tag": "v1.0", "hash": "...", "date": "2026-11-06", "note": "...",
          "aliases": ["14ea026dfc5a"]}]

    ``aliases`` are hashes of the same release computed under an older hash
    rule, so results produced earlier are still labelled correctly.

``workflow_hash``
    Content hash of the folder (code, prompts, config, html; the CHANGELOG
    and ``releases.json`` are excluded). It decides which tag applies: if the
    current hash matches no release, the tag is ``<last tag>+dev`` – the folder
    was edited after the last release. Run ``piaa release <folder> --note ...``
    to turn the current state into the next tag before a run you want to keep.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

RELEASES_FILE = "releases.json"


def package_version() -> str:
    from . import __version__
    return __version__


def load_releases(folder: Path) -> list[dict]:
    p = Path(folder) / RELEASES_FILE
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_releases(folder: Path, releases: list[dict]) -> None:
    (Path(folder) / RELEASES_FILE).write_text(json.dumps(releases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tag_for_hash(version: str, workflow_hash: str, releases: list[dict]) -> str:
    """Tag of a recorded hash, or '' when the hash belongs to no release."""
    for r in releases:
        if workflow_hash and (r.get("hash") == workflow_hash or workflow_hash in r.get("aliases", [])):
            return r["tag"]
    return ""


def current_tag(version: str, workflow_hash: str, releases: list[dict]) -> str:
    """Tag of the folder as it is now: a release tag, or '<last tag>+dev' for unreleased edits."""
    tag = tag_for_hash(version, workflow_hash, releases)
    if tag:
        return tag
    return f"{releases[-1]['tag']}+dev" if releases else f"{version}.0+dev"


def next_tag(version: str, releases: list[dict]) -> str:
    nums = []
    for r in releases:
        try:
            nums.append(int(r["tag"].rsplit(".", 1)[1]))
        except (KeyError, IndexError, ValueError):
            continue
    return f"{version}.{max(nums) + 1 if nums else 0}"


def release(workflow, note: str, tag: str | None = None) -> dict:
    """Record the workflow folder's current hash as a new release tag (no-op if already released)."""
    releases = load_releases(workflow.path)
    existing = tag_for_hash(workflow.version, workflow.hash, releases)
    if existing:
        return next(r for r in releases if r["tag"] == existing)
    entry = {"tag": tag or next_tag(workflow.version, releases), "hash": workflow.hash,
             "date": date.today().isoformat(), "note": note, "package_version": package_version()}
    releases.append(entry)
    save_releases(workflow.path, releases)
    return entry


def stamp(workflow=None) -> dict:
    """Version fields to embed in a manifest."""
    d = {"package_version": package_version()}
    if workflow is not None:
        d.update({"workflow": workflow.version, "workflow_tag": workflow.tag, "workflow_hash": workflow.hash})
    return d


def label_run(workflow: str, workflow_hash: str, workflow_tag: str = "") -> str:
    """Tag for a stored result (falls back to the folder's releases.json, then to 'v1@hash')."""
    if workflow_tag:
        return workflow_tag
    from .workflows import WORKFLOWS_ROOT
    for root in (WORKFLOWS_ROOT, WORKFLOWS_ROOT.parent / "patterns"):
        if (root / workflow).is_dir():
            t = tag_for_hash(workflow, workflow_hash, load_releases(root / workflow))
            if t:
                return t
    return f"{workflow}@{workflow_hash}" if workflow_hash else workflow
