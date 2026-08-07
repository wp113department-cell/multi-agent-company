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
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.fleet.audit_log import AuditEntry, get_audit_log
from app.middleware.rbac import require_authenticated

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _serialize(entry: AuditEntry) -> dict[str, Any]:
    return entry.to_dict()


@router.get("/recent")
async def get_recent_entries(
    limit: int = Query(default=50, ge=1, le=1000),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().recent_async(limit)
    return {"entries": [_serialize(e) for e in entries]}


@router.get("/trace/{trace_id}")
async def get_entries_by_trace(
    trace_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().by_trace_async(trace_id, limit=limit)
    return {"traceId": trace_id, "entries": [_serialize(e) for e in entries]}


@router.get("/task/{task_id}")
async def get_entries_by_task(
    task_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().by_task_async(task_id, limit=limit)
    return {"taskId": task_id, "entries": [_serialize(e) for e in entries]}


@router.get("/approvals")
async def get_approval_entries(
    limit: int = Query(default=100, ge=1, le=1000),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    entries = await get_audit_log().approvals_async(limit=limit)
    return {"entries": [_serialize(e) for e in entries]}
