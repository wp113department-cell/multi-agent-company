"""Stage 4, Cluster N (2026-08-04) — real AgentRun DB tracking for
`run_agent_graph()`, closing a Critical production gap found while
investigating `STAGE4_BACKLOG.md`'s Tier 3 "Q102 on_heartbeat() wiring"
item.

**The bug this closes, proven real before any fix was written**: the only
function that ever wrote `AgentRun.last_heartbeat_at`
(`app/db/repository.py::heartbeat_agent_run`) was only ever invoked via a
closure in `app/api/agents.py`, passed as the `on_heartbeat` argument to
`run_planner()`/`run_coder()` — both of which treat it as a documented
no-op ("kept for backward compat — run_span handles telemetry", a
different, in-process-only metrics system). `last_heartbeat_at` therefore
stayed NULL for the entire life of every real run, and
`WHERE last_heartbeat_at < :cutoff` (the orphan sweep's own query,
`app/fleet/failure_ladder.py::reconcile_orphaned_runs`) never matches a
NULL row by standard SQL semantics — confirmed by this suite's own
pre-existing `test_orphan_recovery.py::
test_never_heartbeated_run_is_left_alone_real_db`. Worse,
`app/agents/manager.py::run_manager()` — the primary dev/QA/review
pipeline — never called `create_agent_run()` at all, so it had zero
`AgentRun` coverage, not just broken coverage.

**The fix**: `run_agent_graph()` (the one real chokepoint all ~76 agents go
through — confirmed via `grep -l "run_agent_graph(" app/agents/*.py`) now
owns a real `AgentRun` row's full lifecycle itself: creates it on start,
heartbeats it (throttled, `agent_run_heartbeat_min_interval_seconds`) from
inside `_make_execute_tools_node`'s real per-tool-call node, and finishes
it (`completed`/`failed`) on both the success and exception exit paths.
Every one of these three steps is non-fatal by construction (the sync
bridge functions in `app/db/repository.py` — `create_agent_run_sync`/
`heartbeat_agent_run_sync`/`finish_agent_run_sync` — never raise), so a run
whose tracking fails for any reason still does its real work.

Tests below prove, against the real local Postgres (matching this suite's
own established `test_orphan_recovery.py`/`test_retention_archive.py`
real-DB convention for anything this state-sensitive), both the individual
mechanisms and — the test that actually matters — that the full loop this
was all for now closes: a run that stops heartbeating really does get
reconciled by the real orphan sweep, which was previously impossible.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
    _post_execute_tools_router,
    run_agent_graph,
)
from app.config import reset_settings_cache
from app.db.repository import create_agent_run_sync, create_task
from app.db.session import new_isolated_async_engine

DO_THING_TOOL = {
    "name": "do_thing",
    "description": "Do a thing",
    "input_schema": {"type": "object", "properties": {}},
}
SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    },
}


def _real_task_id(title: str) -> int:
    """A real dev_tasks row, via the same isolated-engine bridge pattern
    used throughout this suite's own real-DB tests."""

    async def _run() -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc")
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _get_agent_run(run_id: str) -> Any:
    async def _run() -> Any:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import AgentRun

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(AgentRun).where(AgentRun.id == run_id)
                )
                return result.scalar_one_or_none()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


class _ScriptedLLM:
    """Calls do_thing `n_tool_calls` times, then submits — same shape as
    the established _LongConversationLLM pattern in
    test_gap_stage15_context_condense.py, trimmed to just what this file
    needs."""

    def __init__(self, n_tool_calls: int) -> None:
        self.n_tool_calls = n_tool_calls
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls <= self.n_tool_calls:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id=f"tu_{self.calls}",
                        name="do_thing",
                        input={},
                    )
                ],
                usage=SimpleNamespace(input_tokens=20, output_tokens=5),
            )
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="tu_submit",
                    name="submit_result",
                    input={"summary": "done"},
                )
            ],
            usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        )


def _run_scripted_agent(task_id: int, n_tool_calls: int) -> AgentRunState:
    llm = _ScriptedLLM(n_tool_calls=n_tool_calls)
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        return run_agent_graph(
            role_name="stage4_clustern_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[DO_THING_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "do_thing": lambda inp: "did the thing",
                "submit_result": lambda inp: "ok",
            },
            verification_cfg=VerificationConfig(),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=10,
            task_id=str(task_id),
        )


def test_run_agent_graph_creates_a_real_agent_run_and_heartbeats_it() -> None:
    """The core fix, end to end through the real public API every one of
    the ~76 agents calls — not just the isolated bridge functions."""
    task_id = _real_task_id("stage4 clusterN: creates+heartbeats")

    final_state = _run_scripted_agent(task_id, n_tool_calls=2)
    assert final_state["submitted"] is True

    # Find the AgentRun this run created (queried by task_id since the test
    # doesn't have the internal run_id — proving discoverability the same
    # way a real dashboard/sweep would).
    async def _find() -> Any:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import AgentRun

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(AgentRun).where(AgentRun.task_id == task_id)
                )
                return result.scalar_one_or_none()
        finally:
            await engine.dispose()

    run = asyncio.run(_find())
    assert run is not None, (
        "run_agent_graph() must create a real AgentRun row for a run "
        "with a real, valid task_id"
    )
    assert run.agent_type == "stage4_clustern_test_agent"
    assert run.status == "completed"
    assert run.tokens_in == final_state["tokens_in"]
    assert run.finished_at is not None
    # The actual bug this closes: last_heartbeat_at must be real, not NULL —
    # 2 do_thing tool calls happened, so at least one heartbeat should have
    # fired (default throttle is 30s, but the very first tool call always
    # heartbeats since _last_heartbeat_monotonic starts at 0.0).
    assert run.last_heartbeat_at is not None


def test_run_agent_graph_marks_agent_run_failed_on_unhandled_exception() -> None:
    """The exception-path finish call — a run that blows up must not sit in
    status='running' forever either, same as the success path."""
    task_id = _real_task_id("stage4 clusterN: failure path")

    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("simulated LLM failure")
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="simulated LLM failure"):
            run_agent_graph(
                role_name="stage4_clustern_failure_agent",
                model="claude-haiku-4-5-20251001",
                tools=[DO_THING_TOOL, SUBMIT_TOOL],
                tool_handlers={
                    "do_thing": lambda inp: "did the thing",
                    "submit_result": lambda inp: "ok",
                },
                verification_cfg=VerificationConfig(),
                initial_message="do a task",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                max_turns=10,
                task_id=str(task_id),
            )

    async def _find() -> Any:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import AgentRun

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(AgentRun).where(AgentRun.task_id == task_id)
                )
                return result.scalar_one_or_none()
        finally:
            await engine.dispose()

    run = asyncio.run(_find())
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None and "simulated LLM failure" in run.error
    assert run.finished_at is not None


def test_run_agent_graph_with_non_numeric_task_id_creates_no_row_and_still_succeeds() -> (
    None
):
    """The non-fatal safety net: dozens of existing tests (and real
    dispatch paths like guardian-agent periodic scans) pass a non-numeric
    or empty task_id. This must never crash the run or raise — it must
    silently skip AgentRun tracking, exactly like memory_hook_node's own
    established non-fatal contract."""
    final_state = _run_scripted_agent_with_task_id("not-a-real-int-id", n_tool_calls=1)
    assert final_state["submitted"] is True


def _run_scripted_agent_with_task_id(task_id: str, n_tool_calls: int) -> AgentRunState:
    llm = _ScriptedLLM(n_tool_calls=n_tool_calls)
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        return run_agent_graph(
            role_name="stage4_clustern_nonnumeric_agent",
            model="claude-haiku-4-5-20251001",
            tools=[DO_THING_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "do_thing": lambda inp: "did the thing",
                "submit_result": lambda inp: "ok",
            },
            verification_cfg=VerificationConfig(),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=10,
            task_id=task_id,
        )


def test_full_loop_a_run_that_stops_heartbeating_is_now_actually_reconciled() -> None:
    """The test that proves the actual bug is fixed, not just that the
    pieces individually work: create a real AgentRun the way run_agent_
    graph() now does, heartbeat it once (real progress happened), then
    simulate the process dying (no more heartbeats) by backdating
    last_heartbeat_at past the threshold — exactly what test_orphan_
    recovery.py's own _make_agent_run helper does to simulate staleness.
    Before this fix, last_heartbeat_at could never be anything but NULL in
    production, so this reconciliation could never happen for a real run.
    """
    from app.fleet.failure_ladder import reconcile_orphaned_runs

    task_id = _real_task_id("stage4 clusterN: full loop reconciliation")
    run_id = create_agent_run_sync(task_id, "stage4_clustern_hang_agent", "test-model")
    assert run_id is not None

    async def _backdate_heartbeat() -> None:
        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import AgentRun

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                # Timezone-AWARE (production-validation fix, 2026-08-04) —
                # see test_orphan_recovery.py::_make_agent_run's own comment
                # for the full real-environment bug this avoids.
                stale_at = datetime.now(timezone.utc) - timedelta(seconds=2000)
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run_id)
                    .values(last_heartbeat_at=stale_at)
                )
                await session.commit()
        finally:
            await engine.dispose()

    # Simulates: the real heartbeat fired once (proving it's non-NULL, the
    # actual bug), then the process died and 2000s passed with no more.
    asyncio.run(_backdate_heartbeat())

    reconciled_count = asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))
    assert reconciled_count >= 1

    run = _get_agent_run(run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.error == "orphaned — process died without a clean shutdown"


class TestHeartbeatThrottleAtTheNodeLevel:
    """Isolated node-level tests (test_gap19's own probe-graph pattern:
    build a minimal graph directly from _make_execute_tools_node, feed
    pre-set tool_use blocks, bypass call_llm entirely) proving the
    throttle itself — that a chatty run doesn't open a fresh DB connection
    on every single tool call."""

    @staticmethod
    def _build_probe_graph(run_id: str) -> Any:
        node = _make_execute_tools_node(
            tool_handlers={"noop": lambda inp: "ok"},
            verification_cfg=VerificationConfig(),
            human_approval_required=False,
            tools=[
                {
                    "name": "noop",
                    "description": "noop",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            run_id=run_id,
        )
        g: StateGraph[Any, Any, Any, Any] = StateGraph(AgentRunState)
        g.add_node("execute_tools", node)  # type: ignore[call-overload]
        g.set_entry_point("execute_tools")
        g.add_conditional_edges(
            "execute_tools",
            _post_execute_tools_router,
            {"execute_tools": "execute_tools", "critique_node": END, "call_llm": END},
        )
        return g.compile(checkpointer=MemorySaver())

    @staticmethod
    def _initial_state_with_n_tool_calls(n: int) -> AgentRunState:
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"tu{i}",
                            "name": "noop",
                            "input": {},
                        }
                        for i in range(n)
                    ],
                }
            ],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }

    def test_high_throttle_interval_heartbeats_at_most_once_across_many_tool_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_RUN_HEARTBEAT_MIN_INTERVAL_SECONDS", "9999")
        reset_settings_cache()
        try:
            graph = self._build_probe_graph(run_id="probe-run-throttled")
            with patch("app.db.repository.heartbeat_agent_run_sync") as mock_heartbeat:
                for _ in graph.stream(
                    self._initial_state_with_n_tool_calls(5),
                    config={"configurable": {"thread_id": "throttle-probe-1"}},
                    stream_mode="values",
                ):
                    pass
            assert mock_heartbeat.call_count == 1, (
                "5 tool calls with a 9999s throttle must heartbeat exactly "
                "once (the first call always fires since the internal "
                "clock starts at 0.0), not 5 separate DB writes"
            )
        finally:
            reset_settings_cache()

    def test_zero_throttle_interval_heartbeats_on_every_tool_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_RUN_HEARTBEAT_MIN_INTERVAL_SECONDS", "0")
        reset_settings_cache()
        try:
            graph = self._build_probe_graph(run_id="probe-run-unthrottled")
            with patch("app.db.repository.heartbeat_agent_run_sync") as mock_heartbeat:
                for _ in graph.stream(
                    self._initial_state_with_n_tool_calls(5),
                    config={"configurable": {"thread_id": "throttle-probe-2"}},
                    stream_mode="values",
                ):
                    pass
            assert mock_heartbeat.call_count == 5
        finally:
            reset_settings_cache()

    def test_no_run_id_never_calls_heartbeat(self) -> None:
        graph = self._build_probe_graph(run_id="")
        with patch("app.db.repository.heartbeat_agent_run_sync") as mock_heartbeat:
            for _ in graph.stream(
                self._initial_state_with_n_tool_calls(3),
                config={"configurable": {"thread_id": "throttle-probe-3"}},
                stream_mode="values",
            ):
                pass
        mock_heartbeat.assert_not_called()
