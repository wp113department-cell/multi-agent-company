"""Tests for app.agents.temporary_agent — the just-in-time worker barot_agent
spawns, plus TemporaryAgentPool's lifecycle/concurrency management.

TemporaryAgentPool.spawn() only REGISTERS a temp agent — it never executes
the task itself (see the module's own docstring for why: execution happens
later, through whatever real path resolves and invokes the function
registered into dynamic_agent_runtime, exactly like any other agent's
dispatch). These tests reflect that: spawn() is synchronous and immediate;
"execution" is simulated by resolving and calling the registered runtime
function directly, on a thread the TEST controls — mirroring how a real
caller (e.g. specialized_agents.py's background task) would invoke it.

Real Claude API calls are always mocked (patching app.agents.base_graph.
run_agent_graph at its import site inside run_temporary_agent's deferred
import) — these tests never hit the network."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.agents.temporary_agent import (
    TemporaryAgentPool,
    _derive_risk_level,
    make_temporary_agent_tools_and_handlers,
)
from app.fleet.agent_registry import get_agent_registry
from app.fleet.capability_registry import get_capability_registry
from app.fleet.dynamic_agent_runtime import resolve_runtime_agent_fn
from app.fleet.model_router import get_model_router

# ---------------------------------------------------------------------------
# make_temporary_agent_tools_and_handlers
# ---------------------------------------------------------------------------


def test_planned_scope_filters_to_requested_read_only_tools(tmp_path) -> None:
    tools, handlers = make_temporary_agent_tools_and_handlers(
        tool_names=["read_file", "search_code"],
        scope="planned",
        repo_path=str(tmp_path),
    )
    names = {t["name"] for t in tools}
    assert "read_file" in names
    assert "search_code" in names
    assert "submit_temporary_agent_result" in names
    assert "write_file" not in names  # never in READ_ONLY_TOOLS at all
    assert set(handlers.keys()) == {
        "read_file",
        "search_code",
        "submit_temporary_agent_result",
    }


def test_planned_scope_drops_unknown_or_write_tool_names(tmp_path) -> None:
    tools, handlers = make_temporary_agent_tools_and_handlers(
        tool_names=["read_file", "bash", "not_a_real_tool"],
        scope="planned",
        repo_path=str(tmp_path),
    )
    names = {t["name"] for t in tools}
    assert "read_file" in names
    assert "bash" not in names
    assert "not_a_real_tool" not in names


def test_submit_tool_always_present_even_if_not_requested(tmp_path) -> None:
    tools, handlers = make_temporary_agent_tools_and_handlers(
        tool_names=["read_file"], scope="planned", repo_path=str(tmp_path)
    )
    assert "submit_temporary_agent_result" in handlers
    result = handlers["submit_temporary_agent_result"](
        {"summary": "x", "status": "completed"}
    )
    assert "submitted" in result.lower()


def test_full_scope_raises_not_implemented(tmp_path) -> None:
    with pytest.raises(NotImplementedError):
        make_temporary_agent_tools_and_handlers(
            tool_names=["read_file"], scope="full", repo_path=str(tmp_path)
        )


def test_unknown_scope_raises_value_error(tmp_path) -> None:
    with pytest.raises(ValueError):
        make_temporary_agent_tools_and_handlers(
            tool_names=["read_file"], scope="unlimited", repo_path=str(tmp_path)
        )


# ---------------------------------------------------------------------------
# _derive_risk_level
# ---------------------------------------------------------------------------


def test_derive_risk_level_all_low() -> None:
    assert _derive_risk_level(["read_file", "search_code"]) == "low"


def test_derive_risk_level_picks_max() -> None:
    # bash is a real high-risk manifest entry.
    assert _derive_risk_level(["read_file", "bash"]) == "high"


def test_derive_risk_level_ignores_unknown_tools() -> None:
    assert _derive_risk_level(["not_a_real_tool"]) == "low"


def test_derive_risk_level_empty_list() -> None:
    assert _derive_risk_level([]) == "low"


# ---------------------------------------------------------------------------
# TemporaryAgentPool — capacity / spawn / scrap
# ---------------------------------------------------------------------------


def _fake_final_state(submitted: bool = True) -> dict:
    return {
        "submitted": submitted,
        "tokens_in": 10,
        "tokens_out": 20,
        "result": {"summary": "done", "status": "completed", "files_touched": []},
        "verification": {},
    }


@pytest.fixture
def fresh_pool():
    pool = TemporaryAgentPool(max_concurrent=3)
    yield pool
    for slot_name in list(pool._slots.keys()):
        pool.scrap(slot_name, reason="test_cleanup")


def test_has_capacity_true_when_empty(fresh_pool) -> None:
    assert fresh_pool.has_capacity() is True


def test_default_pool_max_concurrent_follows_settings_not_a_literal(
    monkeypatch,
) -> None:
    """AC4 — the process-wide default pool (no constructor override) must
    read barot_agent_max_concurrent_temp_agents live from settings, so
    changing it in config alone changes runtime behavior with zero code
    edits."""
    from app.config import get_settings

    pool = TemporaryAgentPool()  # no override — reads settings each call

    monkeypatch.setattr(get_settings(), "barot_agent_max_concurrent_temp_agents", 1)
    first = pool.spawn(
        task_id="1",
        required_capability="cap_a",
        task_description="a",
        briefing="b",
        tool_names=["read_file"],
        model="m",
        repo_path="/tmp",
    )
    assert first is not None
    assert pool.has_capacity() is False

    monkeypatch.setattr(get_settings(), "barot_agent_max_concurrent_temp_agents", 2)
    assert pool.has_capacity() is True

    pool.scrap(first.role_name, reason="test_cleanup")


def test_spawn_is_synchronous_and_registers_immediately(fresh_pool, tmp_path) -> None:
    """spawn() itself must never execute anything — no Claude call, no
    run_agent_graph call — it only registers. This is the regression test
    for the double-execution bug an earlier version of this module had."""
    with patch("app.agents.base_graph.run_agent_graph") as mock_run:
        slot = fresh_pool.spawn(
            task_id="1",
            required_capability="some_gap_capability",
            task_description="do the thing",
            briefing="use read_file to inspect the repo",
            tool_names=["read_file"],
            model="test-model",
            repo_path=str(tmp_path),
        )
        assert slot is not None
        mock_run.assert_not_called()

    role_name = slot.role_name
    assert get_capability_registry().get(role_name) is not None
    assert get_agent_registry().get(role_name) is not None
    assert get_agent_registry().get(role_name).is_available is True
    assert get_model_router().route(role_name).model == "test-model"
    assert resolve_runtime_agent_fn(role_name) is not None
    assert fresh_pool._role_file_path(role_name).exists()


def test_executing_the_resolved_runtime_fn_completes_and_self_scraps(
    fresh_pool, tmp_path
) -> None:
    """Simulates the real dispatch flow: resolve the registered function
    (as specialized_agents.py's fallback would) and call it directly —
    execution completing must free the slot immediately via
    run_temporary_agent's own finally-block self-scrap."""
    with patch(
        "app.agents.base_graph.run_agent_graph",
        return_value=_fake_final_state(submitted=True),
    ):
        slot = fresh_pool.spawn(
            task_id="1",
            required_capability="some_gap_capability",
            task_description="do the thing",
            briefing="use read_file to inspect the repo",
            tool_names=["read_file"],
            model="test-model",
            repo_path=str(tmp_path),
        )
        assert slot is not None
        role_name = slot.role_name

        run_fn = resolve_runtime_agent_fn(role_name)
        assert run_fn is not None
        result = run_fn(1, "do the thing", str(tmp_path))
        assert result.status == "completed"

    assert get_capability_registry().get(role_name) is None
    assert get_agent_registry().get(role_name) is None
    assert resolve_runtime_agent_fn(role_name) is None
    assert not fresh_pool._role_file_path(role_name).exists()


def test_spawn_declines_at_capacity(fresh_pool) -> None:
    pool = TemporaryAgentPool(max_concurrent=1)
    first = pool.spawn(
        task_id="1",
        required_capability="cap_a",
        task_description="task a",
        briefing="briefing",
        tool_names=["read_file"],
        model="test-model",
        repo_path="/tmp",
    )
    assert first is not None

    second = pool.spawn(
        task_id="2",
        required_capability="cap_b",
        task_description="task b",
        briefing="briefing",
        tool_names=["read_file"],
        model="test-model",
        repo_path="/tmp",
    )
    assert second is None

    pool.scrap(first.role_name, reason="test_cleanup")


def test_scrap_is_idempotent(fresh_pool) -> None:
    slot = fresh_pool.spawn(
        task_id="1",
        required_capability="cap_a",
        task_description="task a",
        briefing="briefing",
        tool_names=["read_file"],
        model="test-model",
        repo_path="/tmp",
    )
    assert slot is not None
    role_name = slot.role_name

    fresh_pool.scrap(role_name, reason="manual")
    assert get_capability_registry().get(role_name) is None
    # Second call must not raise and must be a genuine no-op.
    fresh_pool.scrap(role_name, reason="manual")
    assert get_capability_registry().get(role_name) is None


def test_sweep_expired_reaps_and_frees_slot_while_execution_still_in_flight(
    fresh_pool, tmp_path
) -> None:
    started = threading.Event()

    def _blocking_run(**kwargs):
        started.set()
        # Long enough to safely outlast every assertion below (which all
        # run within milliseconds of started.wait() returning), short
        # enough to keep this leftover daemon thread's lifetime bounded —
        # it deliberately is NOT joined (the whole point of the test is
        # observing state torn down while it's still alive), so it lingers
        # past this test's own end regardless of duration chosen here.
        time.sleep(3)
        return _fake_final_state()

    with patch("app.agents.base_graph.run_agent_graph", side_effect=_blocking_run):
        slot = fresh_pool.spawn(
            task_id="1",
            required_capability="cap_a",
            task_description="task a",
            briefing="briefing",
            tool_names=["read_file"],
            model="test-model",
            repo_path=str(tmp_path),
        )
        assert slot is not None
        role_name = slot.role_name

        run_fn = resolve_runtime_agent_fn(role_name)
        assert run_fn is not None
        exec_thread = threading.Thread(
            target=run_fn, args=(1, "task a", str(tmp_path)), daemon=True
        )
        exec_thread.start()
        started.wait(timeout=5)

        # Force expiry without a real 20-minute wait.
        slot.ttl_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)

        expired = fresh_pool.sweep_expired()
        assert role_name in expired

        # Registry state torn down immediately...
        assert get_capability_registry().get(role_name) is None
        assert get_agent_registry().get(role_name) is None
        assert resolve_runtime_agent_fn(role_name) is None
        # ...even though execution is still (deliberately) in flight
        # elsewhere — this is the documented abandon-not-kill tradeoff.
        assert exec_thread.is_alive()
        assert slot.scrap_reason == "ttl_exceeded"


def test_spawn_uses_unique_names_across_calls(fresh_pool) -> None:
    s1 = fresh_pool.spawn(
        task_id="1",
        required_capability="cap_a",
        task_description="a",
        briefing="b",
        tool_names=["read_file"],
        model="m",
        repo_path="/tmp",
    )
    s2 = fresh_pool.spawn(
        task_id="1",
        required_capability="cap_a",
        task_description="a",
        briefing="b",
        tool_names=["read_file"],
        model="m",
        repo_path="/tmp",
    )
    assert s1 is not None and s2 is not None
    assert s1.role_name != s2.role_name


def test_snapshot_reflects_live_slots(fresh_pool) -> None:
    slot = fresh_pool.spawn(
        task_id="1",
        required_capability="cap_a",
        task_description="a",
        briefing="b",
        tool_names=["read_file"],
        model="m",
        repo_path="/tmp",
    )
    assert slot is not None

    snap = fresh_pool.snapshot()
    assert len(snap) == 1
    assert snap[0]["role_name"] == slot.role_name
    assert snap[0]["required_capability"] == "cap_a"

    fresh_pool.scrap(slot.role_name, reason="test_cleanup")
    assert fresh_pool.snapshot() == []


# ---------------------------------------------------------------------------
# Concurrency: TOCTOU race on has_capacity()-then-spawn()
# ---------------------------------------------------------------------------


def test_concurrent_spawn_never_exceeds_max_concurrent() -> None:
    pool = TemporaryAgentPool(max_concurrent=3)
    results: list = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(10)

    def _attempt(i: int) -> None:
        barrier.wait()
        slot = pool.spawn(
            task_id=str(i),
            required_capability=f"cap_{i}",
            task_description="x",
            briefing="y",
            tool_names=["read_file"],
            model="m",
            repo_path="/tmp",
        )
        with results_lock:
            results.append(slot)

    threads = [threading.Thread(target=_attempt, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    successes = [r for r in results if r is not None]
    assert len(successes) == 3

    for slot in successes:
        pool.scrap(slot.role_name, reason="test_cleanup")
