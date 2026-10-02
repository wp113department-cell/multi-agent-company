"""Qoder cross-check ORCH-04-108 (2026-10-02): an exception escaping the epic
graph was only logged; the epic stayed pending/planning/coding with no reason
and no endpoint could recover it. It is now marked halted with the reason.
Real Postgres; run_epic_manager is patched to raise.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine


def test_crashed_epic_is_halted_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agents.manager as manager
    import app.api.epics as epics_api
    import app.db.session as session_mod

    async def boom(**_k: Any) -> Any:
        raise RuntimeError("simulated graph crash")

    monkeypatch.setattr(manager, "run_epic_manager", boom)

    async def scenario() -> tuple[str, str]:
        engine = new_isolated_async_engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def isolated() -> AsyncIterator[Any]:
            async with factory() as s:
                yield s

        monkeypatch.setattr(session_mod, "get_async_session", isolated)
        eid = str(uuid.uuid4())
        try:
            async with factory() as db:
                await db.execute(
                    text(
                        "INSERT INTO epics (epic_id, title, description, status) "
                        "VALUES (:e, 'qoder 04108', 'goal', 'planning')"
                    ),
                    {"e": eid},
                )
                await db.commit()
            await epics_api._launch_epic_manager(eid, "goal")
            async with factory() as db:
                status, reason = (
                    await db.execute(
                        text(
                            "SELECT status, halt_reason FROM epics WHERE epic_id = :e"
                        ),
                        {"e": eid},
                    )
                ).one()
                await db.execute(
                    text("DELETE FROM epics WHERE epic_id = :e"), {"e": eid}
                )
                await db.commit()
            return str(status), str(reason)
        finally:
            await engine.dispose()

    status, reason = asyncio.run(scenario())
    assert status == "halted", f"epic left in {status!r}"
    assert "simulated graph crash" in reason


def test_epic_list_is_bounded() -> None:
    """Qoder cross-check PROD-09-104: the epic list was unbounded."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        assert c.get("/api/epics?limit=0").status_code == 422
        assert c.get("/api/epics?limit=501").status_code == 422
        r = c.get("/api/epics?limit=2")
        assert r.status_code == 200 and len(r.json()) <= 2
