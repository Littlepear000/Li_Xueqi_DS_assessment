"""Fetch a project's missing documents from the World Bank Documents & Reports API.

Public API ("WDS"), no key required. Called during a run by :class:`piaa.runner.Pipeline`
to complete a project's local documents before extraction: see what is already present,
download the missing wanted types (text only, since the pipeline reads text) into
``<output_dir>/supplement_documents/``, and return them as :class:`DocumentRef` objects
to add to the in-memory index.

Network failures never raise: the run continues with whatever documents exist locally.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode

from .documents import FILENAME_RE, DocumentRef

API_URL = "https://search.worldbank.org/api/v3/wds"
USER_AGENT = "pia-analysis/doc-acquire (World Bank project documents)"
WANTED_CODES = ["PAD", "PID", "ISR", "ProjectPaper", "ProgramDocument"]
TIMEOUT = 60

# WDS document-type name -> local short code (prefix match, case-insensitive)
DOCTY_TO_CODE = [
    ("project appraisal document", "PAD"),
    ("project information and integrated safeguards", "PID"),
    ("project information document", "PID"),
    ("implementation status and results report", "ISR"),
    ("project paper", "ProjectPaper"),
    ("program document", "ProgramDocument"),
    ("programme document", "ProgramDocument"),
]


# ---- HTTP (requests if available, else urllib with certifi) -----------------
def _get_json(url: str) -> dict:
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except ImportError:
        import ssl
        import urllib.request
        ctx = None
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))


def _get_bytes(url: str) -> bytes:
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.content
    except ImportError:
        import ssl
        import urllib.request
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return resp.read()


def _code(docty: str) -> str | None:
    d = (docty or "").strip().lower()
    for name, code in DOCTY_TO_CODE:
        if d.startswith(name):
            return code
    return None


def _norm_date(docdt: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(docdt or "").strip())
    return m.group(1) if m else "unknown"


def _api_documents(project_id: str) -> list[dict]:
    out, offset, rows = [], 0, 100
    while True:
        qs = urlencode({"format": "json", "projectid": project_id, "rows": rows, "os": offset,
                        "fl": "docty,docdt,txturl,id"})
        data = _get_json(f"{API_URL}?{qs}")
        docs = data.get("documents", {}) or {}
        page = [v for k, v in docs.items() if k != "facets" and isinstance(v, dict)]
        out.extend(page)
        try:
            total = int(data.get("total", len(out)))
        except (TypeError, ValueError):
            total = len(out)
        offset += rows
        if len(page) < rows or offset >= total or not page:
            break
    return out


def fetch_missing(project_id: str, existing_keys: set[str], dest_dir: Path,
                  wanted: list[str] | None = None, log=None) -> list[DocumentRef]:
    """Download the wanted document types this project is missing. ``existing_keys`` is the set of
    ``"<code>|<date>"`` already present (updated in place). Returns the new DocumentRefs; [] on any error."""
    wanted = wanted or WANTED_CODES
    out: list[DocumentRef] = []
    try:
        docs = _api_documents(project_id)
    except Exception as e:  # noqa: BLE001 - offline / blocked / API down: keep the run going
        if log:
            log(f"[acquire] {project_id}: WBG API unavailable ({type(e).__name__}); using local documents only")
        return out
    dest_dir = Path(dest_dir)
    for d in docs:
        code = _code(d.get("docty", ""))
        if code is None or code not in wanted:
            continue
        date = _norm_date(d.get("docdt", ""))
        key = f"{code}|{date}"
        if key in existing_keys:
            continue
        txturl = (d.get("txturl") or "").strip()
        if not txturl:
            continue  # text version only; the pipeline reads text
        guid = re.sub(r"\D", "", str(d.get("id") or "")) or str(abs(hash(txturl)) % 10 ** 18)
        fname = f"{project_id}_{code}_{date}_{guid}.txt"
        if not FILENAME_RE.match(fname):
            continue
        dest = dest_dir / fname
        if dest.exists():
            existing_keys.add(key)
            continue
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_get_bytes(txturl))
        except Exception:  # noqa: BLE001
            continue
        existing_keys.add(key)
        out.append(DocumentRef(project_id, code, date, guid, dest, source="api"))
        if log:
            log(f"[acquire] {project_id}: + {code} {date}")
    return out
