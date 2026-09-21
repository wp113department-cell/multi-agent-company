"""Tests for Fleet OS agent_registry.py — Phase F2."""

from __future__ import annotations


from app.fleet.agent_registry import (
    AgentRegistry,
    AgentState,
    get_agent_registry,
)


def _fresh() -> AgentRegistry:
    """Return a new registry for isolated tests."""
    return AgentRegistry()


def test_register_creates_instance_in_sleep_state() -> None:
    r = _fresh()
    inst = r.register("my_agent")
    assert inst.name == "my_agent"
    assert inst.state == AgentState.SLEEP
    assert inst.is_available is True


def test_register_same_name_is_idempotent() -> None:
    r = _fresh()
    i1 = r.register("a")
    i2 = r.register("a")
    assert i1 is i2


def test_start_task_sets_running_state() -> None:
    r = _fresh()
    r.register("a")
    inst = r.start_task("a", "task-001")
    assert inst.state == AgentState.RUNNING
    assert inst.current_task_id == "task-001"
    assert inst.is_available is False


def test_complete_task_moves_to_sleep() -> None:
    r = _fresh()
    r.start_task("a", "task-001")
    inst = r.complete_task("a")
    assert inst.state == AgentState.SLEEP
    assert inst.current_task_id is None
    assert inst.is_available is True


def test_fail_task_increments_error_count() -> None:
    r = _fresh()
    r.register("a")
    r.start_task("a", "task-001")
    inst = r.fail_task("a", "timeout")
    assert inst.state == AgentState.ERROR
    assert inst.error_count == 1
    # UPDATED (verification batch B8, #444-#446): one failure makes the agent "degraded", which is
    # still selectable (scored at 0.5) — it used to be benched for good because state stayed ERROR
    assert inst.is_available is True


def test_three_failures_marks_unhealthy() -> None:
    r = _fresh()
    r.register("a")
    for i in range(3):
        r.start_task("a", f"task-{i}")
        r.fail_task("a", "timeout")
    inst = r.get("a")
    assert inst.health == "unhealthy"
    assert inst.is_available is False


def test_recover_resets_health() -> None:
    r = _fresh()
    r.register("a")
    for i in range(3):
        r.start_task("a", f"task-{i}")
        r.fail_task("a", "timeout")
    r.get("a").recover()
    assert r.get("a").health == "healthy"
    assert r.get("a").is_available is True


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH16 §88 gap-closure (2026-08-11)
# ---------------------------------------------------------------------------


def test_one_or_two_failures_marks_degraded_not_unhealthy() -> None:
    """ "degraded" was a real value in FleetManager.select()'s health_weight
    dict but AgentInstance.fail() only ever wrote "healthy" or "unhealthy" —
    confirmed unreachable before this gap-closure. 1-2 consecutive errors
    should land on the real middle tier."""
    r = _fresh()
    r.register("a")
    r.start_task("a", "task-0")
    inst = r.fail_task("a", "timeout")
    assert inst.health == "degraded"
    assert inst.is_available is True  # UPDATED (B8): degraded stays selectable

    r.start_task("a", "task-1")
    inst = r.fail_task("a", "timeout again")
    assert inst.health == "degraded"

    r.start_task("a", "task-2")
    inst = r.fail_task("a", "third strike")
    assert inst.health == "unhealthy"


def test_recover_task_is_noop_when_already_healthy() -> None:
    r = _fresh()
    r.register("a")
    inst = r.recover_task("a")
    assert inst.health == "healthy"


def test_recover_task_clears_degraded_and_unhealthy() -> None:
    r = _fresh()
    r.register("a")
    r.start_task("a", "task-0")
    r.fail_task("a", "timeout")
    assert r.get("a").health == "degraded"

    r.recover_task("a")
    assert r.get("a").health == "healthy"
    assert r.get("a").error_count == 0


def test_recover_task_unknown_agent_returns_none() -> None:
    r = _fresh()
    assert r.recover_task("does-not-exist") is None


def test_reseed_health_from_events_reapplies_unhealthy() -> None:
    """AUDIT_Q_BATCH16 §89 gap-closure — real Postgres round trip: a
    persisted "unhealthy" health_updated event must re-seed a fresh
    AgentRegistry's AgentInstance so retirement survives a process restart
    instead of silently resetting."""
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Event
    from app.fleet.agent_registry import reseed_health_from_events

    agent_name = "td-batch16-reseed-agent"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(Event).where(Event.emitted_by == agent_name)
                )
                session.add(
                    Event(
                        event_id="11111111-1111-1111-1111-111111111111",
                        event_type="agent.health_updated",
                        emitted_by=agent_name,
                        payload={"health": "unhealthy", "state": "3 strikes"},
                    )
                )
                await session.commit()

                # reseed_health_from_events scans every agent's latest
                # persisted event (not just this test's), so `seeded` may
                # legitimately be >1 in a shared dev DB with other agents'
                # own real unhealthy history — this test only asserts on
                # its own uniquely-named agent's resulting state, not the
                # aggregate count. Writes onto the process-global registry
                # (get_agent_registry()'s own singleton).
                from app.fleet.agent_registry import get_agent_registry

                seeded = await reseed_health_from_events(session)
                assert seeded >= 1
                inst = get_agent_registry().get(agent_name)
                assert inst is not None
                assert inst.health == "unhealthy"
                assert inst.is_available is False
        finally:
            await session.execute(delete(Event).where(Event.emitted_by == agent_name))
            await session.commit()
            await engine.dispose()

    asyncio.run(_run())


def test_reseed_health_from_events_ignores_healthy_agents() -> None:
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Event
    from app.fleet.agent_registry import get_agent_registry, reseed_health_from_events

    agent_name = "td-batch16-reseed-healthy-agent"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(Event).where(Event.emitted_by == agent_name)
                )
                session.add(
                    Event(
                        event_id="22222222-2222-2222-2222-222222222222",
                        event_type="agent.health_updated",
                        emitted_by=agent_name,
                        payload={"health": "healthy", "state": "sleep"},
                    )
                )
                await session.commit()

                await reseed_health_from_events(session)
                # A "healthy" event must not spuriously mark THIS agent
                # unhealthy — only a real persisted "unhealthy" event does.
                inst = get_agent_registry().get(agent_name)
                assert inst is None or inst.health != "unhealthy"
        finally:
            await session.execute(delete(Event).where(Event.emitted_by == agent_name))
            await session.commit()
            await engine.dispose()

    asyncio.run(_run())


def test_fail_task_fires_alert_only_on_healthy_to_unhealthy_transition(
    monkeypatch,
) -> None:
    """AUDIT_Q_BATCH16 §89 gap-closure — "Notify a supervisor" on automatic
    retirement. Fired exactly once, only at the real 3rd-strike transition,
    never on every fail_task() call (degraded transitions are not
    retirement)."""
    import app.fleet.agent_registry as agent_registry_module

    calls: list[tuple[str, str]] = []

    def _fake_notify(agent_name: str, reason: str) -> None:
        calls.append((agent_name, reason))

    monkeypatch.setattr(agent_registry_module, "_notify_agent_retired", _fake_notify)  # type: ignore[attr-defined]

    r = _fresh()
    r.register("a")
    for i in range(3):
        r.start_task("a", f"task-{i}")
        r.fail_task("a", f"failure {i}")

    assert len(calls) == 1
    assert calls[0][0] == "a"

    # A subsequent failure (already unhealthy) must not re-fire the alert.
    r.start_task("a", "task-3")
    r.fail_task("a", "failure 3")
    assert len(calls) == 1


def test_available_returns_only_idle_or_sleep() -> None:
    r = _fresh()
    r.register("a")
    r.register("b")
    r.start_task("b", "task-b")
    available = r.available()
    names = [i.name for i in available]
    assert "a" in names
    assert "b" not in names


def test_running_returns_only_running() -> None:
    r = _fresh()
    r.register("a")
    r.register("b")
    r.start_task("b", "task-b")
    running = r.running()
    assert len(running) == 1
    assert running[0].name == "b"


def test_snapshot_returns_serializable_dicts() -> None:
    r = _fresh()
    r.register("x")
    snap = r.snapshot()
    assert isinstance(snap, list)
    assert snap[0]["name"] == "x"
    assert "state" in snap[0]
    assert "is_available" in snap[0]


def test_total_runs_increments() -> None:
    r = _fresh()
    r.register("a")
    r.start_task("a", "t1")
    r.complete_task("a")
    r.start_task("a", "t2")
    r.complete_task("a")
    assert r.get("a").total_runs == 2


# ---- Singleton pre-registered reference agents ----


def test_reference_agents_pre_registered_in_sleep() -> None:
    r = get_agent_registry()
    for name in ("pm", "bug_fix", "qa"):
        inst = r.get(name)
        assert inst is not None, f"{name} not pre-registered"
        assert inst.state == AgentState.SLEEP


# ---- deregister() — added for barot_agent's temporary_agent teardown ----


def test_deregister_removes_instance() -> None:
    r = _fresh()
    r.register("temp1")
    removed = r.deregister("temp1")
    assert removed is not None
    assert removed.name == "temp1"
    assert r.get("temp1") is None


def test_deregister_missing_returns_none() -> None:
    r = _fresh()
    assert r.deregister("never_registered") is None


def test_deregister_is_idempotent() -> None:
    r = _fresh()
    r.register("temp2")
    assert r.deregister("temp2") is not None
    assert r.deregister("temp2") is None


def test_deregister_does_not_publish_lifecycle_event(monkeypatch) -> None:
    """A scrapped temp agent is routine cleanup, not a governance event —
    unlike disable()/retire(), deregister() must never fire the lifecycle
    notification/event path."""
    import app.fleet.agent_registry as agent_registry_module

    calls: list[str] = []
    monkeypatch.setattr(
        agent_registry_module,
        "_publish_lifecycle_event",
        lambda name, inst: calls.append(name),
    )
    monkeypatch.setattr(
        agent_registry_module,
        "_notify_agent_retired",
        lambda name, reason: calls.append(name),
    )

    r = _fresh()
    r.register("temp3")
    r.deregister("temp3")
    assert calls == []


def test_deregister_does_not_affect_reference_agents() -> None:
    r = get_agent_registry()
    r.register("temp4")
    r.deregister("temp4")
    for name in ("pm", "bug_fix", "qa"):
        assert r.get(name) is not None
