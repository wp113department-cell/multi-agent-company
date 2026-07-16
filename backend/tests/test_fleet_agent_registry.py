"""Tests for Fleet OS agent_registry.py — Phase F2."""
from __future__ import annotations

import pytest

from app.fleet.agent_registry import (
    AgentInstance,
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
    assert inst.is_available is False


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
