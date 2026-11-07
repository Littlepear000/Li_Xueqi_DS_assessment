"""Build a clean release zip of the PIA Analysis package.

Run from inside the package folder:  python package_release.py
Produces  PIA_Analysis_<version>.zip  in the parent folder, containing the package
under a top-level "PIA Analysis/" directory, with build/runtime/private files excluded.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent            # the package folder (contains pyproject.toml)
TOP = "PIA Analysis"                               # top-level folder name inside the zip

# directories excluded anywhere in the tree
EXCLUDE_DIRS = {".venv", "output", "__pycache__", ".git", ".pytest_cache", ".idea",
                "piaa.egg-info", "_download_reports"}
# exact relative paths excluded
EXCLUDE_FILES = {"config/local.env"}
# filename patterns excluded anywhere
EXCLUDE_SUFFIXES = (".pyc", ".pyo")
EXCLUDE_NAMES = {"_judge_cache.json", "_verify_cache.json", ".DS_Store"}


def version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "piaa" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0.0"


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS:
        return False
    if rel.as_posix() in EXCLUDE_FILES:
        return False
    if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_NAMES:
        return False
    return True


def main() -> int:
    ver = version()
    out = ROOT.parent / f"PIA_Analysis_{ver}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            if p.is_dir() or not included(p):
                continue
            z.write(p, f"{TOP}/{p.relative_to(ROOT).as_posix()}")
            n += 1
    print(f"Wrote {out}  ({n} files, PIA Analysis {ver})")
    print("Excluded: .venv, output, __pycache__, *.pyc, config/local.env, caches, .git, egg-info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
