"""Qoder cross-check H-5 (2026-10-02): approving an epic's cost could never
start it. approve-cost reset the epic to pending and relaunched the manager,
whose cost node re-estimated the same over-threshold cost and halted at
pending_cost_approval again — forever. The approval is now recorded
(migration 063) and the gate honours it while the estimate stays within the
approved amount. Real Postgres; the relaunch is not executed.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine


async def _make_epic(status: str, estimate: str | None, approved: str | None) -> str:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            eid = str(uuid.uuid4())
            await db.execute(
                text(
                    "INSERT INTO epics (epic_id, title, description, status, cost_estimate, "
                    "cost_approved_usd) VALUES (:e, 'qoder h5', 'x', :s, :c, :a)"
                ),
                {"e": eid, "s": status, "c": estimate, "a": approved},
            )
            await db.commit()
            return eid
    finally:
        await engine.dispose()


async def _row(eid: str) -> Any:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            return (
                await db.execute(
                    text(
                        "SELECT status, cost_approved_usd, cost_approved_by FROM epics "
                        "WHERE epic_id = :e"
                    ),
                    {"e": eid},
                )
            ).one()
    finally:
        await engine.dispose()


async def _drop(eids: list[str]) -> None:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text("DELETE FROM epics WHERE epic_id = ANY(:e)"), {"e": eids}
            )
            await db.commit()
    finally:
        await engine.dispose()


def test_approve_cost_records_the_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.epics as epics_api
    from app.main import app

    async def no_launch(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(epics_api, "_launch_epic_manager", no_launch)
    eid = asyncio.run(_make_epic("pending_cost_approval", "4.2", None))
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/api/epics/{eid}/approve-cost", headers={"X-User-Id": "approver-1"}
            )
        assert r.status_code == 200, r.text
        status, approved_usd, approved_by = asyncio.run(_row(eid))
        assert status == "pending"
        assert approved_usd == Decimal("4.2000")
        assert approved_by
    finally:
        asyncio.run(_drop([eid]))


def _gate(eid: str, estimate_usd: float, monkeypatch: pytest.MonkeyPatch) -> str:
    import app.pipeline.cost_controller as cc
    from app.agents.manager import _cost_estimate_node

    real = cc.estimate_epic_cost

    async def fixed(subtask_count: int, db: Any) -> Any:
        base = await real(subtask_count=subtask_count, db=db)
        return replace(base, estimated_cost_usd=estimate_usd, requires_approval=True)

    monkeypatch.setattr(cc, "estimate_epic_cost", fixed)

    async def run() -> str:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                out = await _cost_estimate_node({"epic_id": eid, "db": db})  # type: ignore[typeddict-item]
                return str(out.get("stage", ""))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_gate_lets_an_approved_epic_through(monkeypatch: pytest.MonkeyPatch) -> None:
    approved = asyncio.run(_make_epic("pending", "4.2", "4.2"))
    never = asyncio.run(_make_epic("pending", None, None))
    grown = asyncio.run(_make_epic("pending", "4.2", "4.2"))
    try:
        assert _gate(approved, 4.2, monkeypatch) == "", "approved epic re-blocked"
        assert _gate(never, 4.2, monkeypatch) == "pending_cost_approval"
        assert (
            _gate(grown, 9.9, monkeypatch) == "pending_cost_approval"
        ), "an estimate above the approved amount must ask again"
    finally:
        asyncio.run(_drop([approved, never, grown]))
