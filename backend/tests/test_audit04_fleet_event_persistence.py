"""Production audit 2026-09-29 — Fleet OS events reach the `events` table.

Before the fix the Fleet OS -> legacy bus forward called publish_event()
without a DB session, so nothing was persisted: the live dev database had 0
`agent.health_updated` rows despite thousands of agent runs, and
reseed_health_from_events() — which is what makes an admin's agent
disable/retire survive a restart — always found nothing.

Real app lifespan (captured main loop), real endpoint, real Postgres.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Event
from app.db.session import new_isolated_async_engine
from app.fleet.agent_registry import (
    AgentState,
    get_agent_registry,
    reseed_health_from_events,
)
from app.main import app

AGENT = "style_reviewer"


def _latest_health_event(since: datetime) -> dict | None:
    async def _q() -> dict | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine)() as s:
                row = (
                    await s.execute(
                        select(Event.payload)
                        .where(
                            Event.event_type == "agent.health_updated",
                            Event.emitted_by == AGENT,
                            Event.created_at >= since,
                        )
                        .order_by(Event.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                return row
        finally:
            await engine.dispose()

    return asyncio.run(_q())


def _cleanup(since: datetime) -> None:
    async def _d() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine)() as s:
                await s.execute(
                    delete(Event).where(
                        Event.emitted_by == AGENT, Event.created_at >= since
                    )
                )
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_d())


def test_disable_is_persisted_and_survives_a_restart() -> None:
    since = datetime.now(timezone.utc) - timedelta(seconds=1)
    registry = get_agent_registry()
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/api/agents/{AGENT}/lifecycle",
                json={"action": "disable", "reason": "audit persistence test"},
            )
            assert r.status_code == 200, r.text

            payload = None
            for _ in range(50):  # forwarded on the app loop — allow it to land
                payload = _latest_health_event(since)
                if payload:
                    break
                time.sleep(0.1)
        assert payload is not None, "agent.health_updated was never persisted"
        assert payload.get("state") == AgentState.DISABLED.value

        # simulate a process restart: forget the in-memory state, then reseed
        registry._instances.pop(AGENT, None)

        async def _reseed() -> int:
            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(engine)() as s:
                    return await reseed_health_from_events(s)
            finally:
                await engine.dispose()

        assert asyncio.run(_reseed()) >= 1
        instance = registry.get(AGENT)
        assert instance is not None and instance.state == AgentState.DISABLED
    finally:
        registry.reactivate(AGENT)
        _cleanup(since)
