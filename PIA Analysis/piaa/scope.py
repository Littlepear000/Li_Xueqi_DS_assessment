"""Project scope rules (workflow ``scope:`` block).

A project is out of scope when its approval date is before ``min_approval_date`` (calendar date, ``YYYY-MM-DD``),
when its status is in ``exclude_status`` (case-insensitive), or when the approval date is missing and
``keep_missing_date`` is false. Out-of-scope projects are not read and get no model calls; their record carries
``error = "out of scope: <reason>"`` and the web app shows them with review status ``out of scope``.
"""
from __future__ import annotations

OUT_OF_SCOPE = "out of scope"


def scope_reason(cfg: dict | None, project) -> str:
    """'' when the project is in scope, else a short reason."""
    cfg = cfg or {}
    status = (getattr(project, "status", "") or "").strip()
    excluded = {s.lower() for s in cfg.get("exclude_status", []) or []}
    if status.lower() in excluded:
        return f"status {status}"
    min_date = str(cfg.get("min_approval_date") or "").strip()
    date = (getattr(project, "approval_date", "") or "").strip()
    if min_date:
        if not date:
            if not cfg.get("keep_missing_date", False):
                return "no approval date"
        elif date[:10] < min_date[:10]:
            return f"approved {date[:10]} (before {min_date[:10]})"
    return ""


def is_out_of_scope_error(error: str | None) -> bool:
    return bool(error) and error.startswith(OUT_OF_SCOPE)
