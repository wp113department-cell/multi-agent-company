"""Audit Log API — AUDIT_Q_BATCH11 §96 "Audit logs".

Read-only endpoints over app/fleet/audit_log.py's new DB-backed query
methods (recent_async/by_trace_async/by_task_async) — before this, there
was no API route reaching AuditLog's query surface at all (confirmed by
grep: zero callers of recent()/by_trace()/by_task() anywhere in app/),
which made the audit trail effectively write-only despite being real and
durably persisted. All routes require an authenticated caller (internal
governance/incident data, not public) — matching the same
require_authenticated tier used elsewhere for internal-state-exposing GET
routes (artifacts, metrics, console, settings, approvals).

AUDIT_Q_BATCH14 §48 gap-closure — the audit's "2000-entry in-memory cap"
finding was stale (the DB-backed query these routes already call has no
such cap — the ring buffer it falls back to during a DB outage does), but
these routes themselves had no way to page past a single `limit`-sized
response. Each route now accepts an optional `before` cursor (an entry
timestamp, ISO-8601) and returns `next_cursor` — the timestamp to pass as
`before` on the next call — whenever a full page comes back, so a caller
can walk the entire unbounded history page by page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.fleet.audit_log import AuditEntry, get_audit_log
from app.middleware.rbac import require_authenticated

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _serialize(entry: AuditEntry) -> dict[str, Any]:
    return entry.to_dict()


def _cursor_str(ts: datetime | str) -> str:
    # AuditEntry.timestamp is a real datetime when reconstructed from a DB
    # row (_row_to_entry) but a pre-formatted ISO string on the in-memory
    # ring-buffer fallback path (AuditLog._now() — audit_log.py) — normalize
    # either into the same ISO string shape so it round-trips through the
    # `before` query param (parsed back into a datetime by FastAPI) either way.
    return ts.isoformat() if isinstance(ts, datetime) else ts


def _paginated(entries: list[AuditEntry], limit: int) -> dict[str, Any]:
    next_cursor = _cursor_str(entries[-1].timestamp) if len(entries) == limit else None
    return {
        "entries": [_serialize(e) for e in entries],
        "next_cursor": next_cursor,
    }


@router.get("/recent")
async def get_recent_entries(
    limit: int = Query(default=50, ge=1, le=1000),
    before: datetime | None = Query(default=None),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().recent_async(limit, before=before)
    return _paginated(entries, limit)


@router.get("/trace/{trace_id}")
async def get_entries_by_trace(
    trace_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    before: datetime | None = Query(default=None),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().by_trace_async(trace_id, limit=limit, before=before)
    return {"traceId": trace_id, **_paginated(entries, limit)}


@router.get("/task/{task_id}")
async def get_entries_by_task(
    task_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    before: datetime | None = Query(default=None),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().by_task_async(task_id, limit=limit, before=before)
    return {"taskId": task_id, **_paginated(entries, limit)}


@router.get("/approvals")
async def get_approval_entries(
    limit: int = Query(default=100, ge=1, le=1000),
    before: datetime | None = Query(default=None),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().approvals_async(limit=limit, before=before)
    return _paginated(entries, limit)


@router.get("/verify")
async def verify_audit_chain(
    since_seq: int = Query(default=1, ge=1),
    max_rows: int = Query(default=200_000, ge=1, le=1_000_000),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """AUDIT_Q_BATCH18 Bonus-table row 7 gap-closure — the one real call
    site AuditLog.verify_chain() needed: migration 036 already gives
    audit_log a genuine DB-enforced hash chain and append-only triggers,
    but nothing ever exposed a way to actually check the chain is intact.
    `since_seq` (default: from the very beginning) enables a cheap
    incremental check — pass the `seq` returned by a prior call's last
    checked entry to only re-verify what's been written since.
    `intact: null` (not true/false) means the check itself failed (DB
    unreachable, or a pre-migration-036 table) — distinct from a
    confirmed-broken chain, so a caller never mistakes "couldn't verify"
    for "verified clean"."""
    return await get_audit_log().verify_chain(since_seq=since_seq, max_rows=max_rows)
