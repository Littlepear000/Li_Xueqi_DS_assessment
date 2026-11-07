"""Reviewer-curated approach examples (few-shot reference for extraction).

Stored as ``<output_dir>/approach_examples.json`` (legacy: ``<raw_dir>/approach_examples.json``) so the same examples serve every
folder and workflow version:

    {"enabled": true, "updated_at": "...",
     "good": [{"text": "...", "category": "Technological", "note": "...", "project_id": "P123456"}, ...],
     "bad":  [{"text": "...", "category": "",               "note": "why it is not an approach", "project_id": ""}, ...]}

``prompt_block()`` renders them for the classification system prompt; ``fingerprint()`` is recorded in the
run trace so every result shows which example set it was produced with.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "approach_examples.json"
FIELDS = ("text", "category", "note", "project_id")
CATEGORIES = ("Operational", "Technological", "Financial", "Collaborative")


def path_for(base_dir: str | Path) -> Path:
    return Path(base_dir) / FILE_NAME


def _clean(rows) -> list[dict]:
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        row = {k: str(r.get(k, "") or "").strip() for k in FIELDS}
        if row["text"]:
            out.append(row)
    return out


def load(base_dir: str | Path, legacy_dir: str | Path | None = None) -> dict:
    p = path_for(base_dir)
    if not p.exists() and legacy_dir is not None and path_for(legacy_dir).exists():
        p = path_for(legacy_dir)   # read the old raw_data location until the reviewer saves again
    data = {"enabled": True, "updated_at": "", "good": [], "bad": []}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            data.update(enabled=bool(raw.get("enabled", True)), updated_at=raw.get("updated_at", ""),
                        good=_clean(raw.get("good")), bad=_clean(raw.get("bad")))
        except (json.JSONDecodeError, OSError):
            pass
    data["path"] = str(p)
    data["fingerprint"] = fingerprint(data)
    return data


def save(base_dir: str | Path, data: dict) -> dict:
    out = {"enabled": bool(data.get("enabled", True)),
           "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "good": _clean(data.get("good")), "bad": _clean(data.get("bad"))}
    p = path_for(base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return load(base_dir)


def fingerprint(data: dict) -> str:
    if not data.get("enabled", True) or not (data.get("good") or data.get("bad")):
        return ""
    raw = json.dumps({"good": data.get("good", []), "bad": data.get("bad", [])}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def prompt_block(base_dir: str | Path, max_each: int = 25, legacy_dir: str | Path | None = None) -> tuple[str, dict]:
    """Text appended to the classification system prompt, plus a small summary for the run trace."""
    data = load(base_dir, legacy_dir)
    if not data["enabled"] or not (data["good"] or data["bad"]):
        return "", {"examples": "none"}
    lines = ["", "## Reference examples from human reviewers",
             "Reviewers labelled the passages below. Use them to calibrate what counts as an approach; "
             "they illustrate the definition above and do not replace it. Do not copy their wording into your answers."]
    if data["good"]:
        lines += ["", "### GOOD examples - these ARE approaches"]
        for i, r in enumerate(data["good"][:max_each], 1):
            lines.append(f"{i}. [{r['category'] or 'category not given'}] \"{r['text']}\"" + (f" - {r['note']}" if r["note"] else ""))
    if data["bad"]:
        lines += ["", "### BAD examples - these are NOT approaches"]
        for i, r in enumerate(data["bad"][:max_each], 1):
            lines.append(f"{i}. \"{r['text']}\"" + (f" - why not: {r['note']}" if r["note"] else ""))
    return "\n".join(lines) + "\n", {"examples": data["fingerprint"], "good": min(len(data["good"]), max_each), "bad": min(len(data["bad"]), max_each)}


def with_examples(ctx, trace, system: str) -> str:
    """Append the reviewer examples to a workflow's system prompt and record the example set in the step trace.
    Used by the extraction / classification steps (v4 classify, v5-v6 extract and validate).
    Workflow config can switch it off: ``examples: {enabled: false}`` or limit it: ``examples: {max_each: 10}``."""
    cfg = ctx.cfg("examples", {}) or {}
    if not cfg.get("enabled", True):
        return system
    text, info = prompt_block(ctx.settings.output_dir, cfg.get("max_each", 25), legacy_dir=ctx.settings.raw_dir)
    if trace is not None:
        trace.output.update(info)
    return system + text
