"""Approval Gate — Day 13.

Pure tracking/indexing over interrupt()-paused threads. Does NOT call
interrupt() itself — the actual pause mechanics already exist and are
proven correct in app/pipeline/graph.py (real AsyncPostgresSaver checkpointer
+ interrupt_before, exercised end-to-end in Day 12's smoke test). This module
is the generic layer any interrupt() call site registers into, so
GET /api/approvals/pending doesn't need to enumerate every possible thread —
it just reads this table.

Verified empirically before writing this (see docs/DAY13_PLAN.md): LangGraph
re-runs a node's entire body from the top on Command(resume=...), so
record_pending() must be called by the code that invokes the graph, exactly
once, after invoke() confirms a real pause — never from inside the paused
node itself.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import get_settings


@dataclass
class PendingApprovalRecord:
    id: int
    thread_id: str
    task_id: int | None
    agent_name: str
    action: str
    details: dict[str, Any]
    status: str
    created_at: str
    decided_at: str | None
    decided_by: str | None


def _to_record(row: Any) -> PendingApprovalRecord:
    return PendingApprovalRecord(
        id=row.id,
        thread_id=row.thread_id,
        task_id=row.task_id,
        agent_name=row.agent_name,
        action=row.action,
        details=dict(row.details or {}),
        status=row.status,
        created_at=row.created_at.isoformat() if row.created_at else "",
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        decided_by=row.decided_by,
    )


def _new_isolated_db_engine() -> Any:
    """A throwaway async engine, never the shared app.db.session singleton —
    see feedback_asyncio_isolated_engine: reusing one engine across multiple
    asyncio.run() calls in the same process raises 'attached to a different
    loop'. A fresh, disposed-after-use engine per call is always correct."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _record_pending(
    thread_id: str, action: str, details: dict[str, Any], agent_name: str, task_id: int | None
) -> Any:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PendingApproval

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = PendingApproval(
                thread_id=thread_id, task_id=task_id, agent_name=agent_name,
                action=action, details=details, status="pending",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row
    finally:
        await engine.dispose()


async def _list_pending() -> list[Any]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PendingApproval

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                await session.execute(
                    select(PendingApproval)
                    .where(PendingApproval.status == "pending")
                    .order_by(PendingApproval.created_at.desc())
                )
            ).scalars().all()
            return list(rows)
    finally:
        await engine.dispose()


async def _get_pending(thread_id: str) -> Any:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PendingApproval

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return (
                await session.execute(
                    select(PendingApproval)
                    .where(PendingApproval.thread_id == thread_id)
                    .order_by(PendingApproval.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


async def _record_decision(thread_id: str, approved: bool, decided_by: str) -> Any:
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PendingApproval

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(PendingApproval)
                    .where(PendingApproval.thread_id == thread_id, PendingApproval.status == "pending")
                    .order_by(PendingApproval.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            await session.execute(
                update(PendingApproval)
                .where(PendingApproval.id == row.id)
                .values(
                    status="approved" if approved else "rejected",
                    decided_at=datetime.now().astimezone(),
                    decided_by=decided_by,
                )
            )
            await session.commit()
            await session.refresh(row)
            return row
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Sync facades — asyncio.run() per call, for sync callers (tests, sync code
# paths). MUST NOT be called from inside an already-running event loop
# (raises RuntimeError) — api/agents.py's launch_planning_pipeline/
# resume_planning_pipeline are themselves async (run via FastAPI
# BackgroundTasks inside the live loop), so they use the async variants below
# instead. Found this the hard way: the sync facades failed silently there
# (caught by a broad except Exception at the call site) until fixed.
# ---------------------------------------------------------------------------

def record_pending(
    thread_id: str, action: str, details: dict[str, Any] | None = None,
    agent_name: str = "", task_id: int | None = None,
) -> PendingApprovalRecord:
    row = asyncio.run(_record_pending(thread_id, action, details or {}, agent_name, task_id))
    return _to_record(row)


def list_pending() -> list[PendingApprovalRecord]:
    rows = asyncio.run(_list_pending())
    return [_to_record(r) for r in rows]


def get_pending(thread_id: str) -> PendingApprovalRecord | None:
    row = asyncio.run(_get_pending(thread_id))
    return _to_record(row) if row is not None else None


def record_decision(thread_id: str, approved: bool, decided_by: str = "user") -> PendingApprovalRecord | None:
    row = asyncio.run(_record_decision(thread_id, approved, decided_by))
    return _to_record(row) if row is not None else None


# ---------------------------------------------------------------------------
# Async facades — for callers already running inside an event loop
# ---------------------------------------------------------------------------

async def arecord_pending(
    thread_id: str, action: str, details: dict[str, Any] | None = None,
    agent_name: str = "", task_id: int | None = None,
) -> PendingApprovalRecord:
    row = await _record_pending(thread_id, action, details or {}, agent_name, task_id)
    return _to_record(row)


async def alist_pending() -> list[PendingApprovalRecord]:
    rows = await _list_pending()
    return [_to_record(r) for r in rows]


async def aget_pending(thread_id: str) -> PendingApprovalRecord | None:
    row = await _get_pending(thread_id)
    return _to_record(row) if row is not None else None


async def arecord_decision(thread_id: str, approved: bool, decided_by: str = "user") -> PendingApprovalRecord | None:
    row = await _record_decision(thread_id, approved, decided_by)
    return _to_record(row) if row is not None else None
