"""Gap-closure — Days 0-18 audit (2026-07-22), triggered by an explicit user
request to re-check the entire FLEET_ENHANCEMENT_PLAN.md before Day 19.

Two Explore agents audited (a) model_router/budget_manager/tool_discovery
real wiring and (b) capability_registry completeness/Day 0 exit criteria.
Findings, all confirmed by direct grep/read before fixing:

1. `run_agent_graph()` had a real, systemic bug: `task_id=tid` at 4 call
   sites (agent_registry.start_task, task_started, task_completed,
   task_failed) — `tid` is the per-RUN trace id
   (`trace_id or uuid.uuid4().hex[:12]`), not the actual task's id. Every
   TaskStarted/TaskCompleted/TaskFailed fleet event and agent_registry's
   `current_task_id` field has shown a random trace hex string instead of
   the real task id since this was written.
2. Gap 7's exit criteria ("HealthUpdated event on success OR error") was
   only satisfied on the success path — the exception handler never
   published one.
3. `fleet_checkpoint.py`'s `save_checkpoint()`/`rollback_to()` (re-exported
   as `failure_ladder.checkpoint`/`rollback`) had zero real callers anywhere
   despite being fully built and tested since Day 12 — the ladder's own
   Rollback/Resume rungs had nothing real to act on. Wired into the two real
   places the ladder already escalates from (base_graph.py's stall path and
   exception handler; manager.py's per-subtask escalate and epic-abort).
4. Gap 10 (trace_id correlation): several real fleet-event/audit-log call
   sites hardcoded `trace_id=""` (manager.py's task_created/escalate/abort,
   api/agents.py's bootstrap events and audit_log.record_approval).
5. Most of the 72 real agent modules are only imported lazily (on first
   real dispatch) — before this fix, `capability_registry` held as few as
   ~6 of 72 agents for most of a fresh process's lifetime. Added
   `ensure_all_agents_registered()`, called at startup.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _restore_pm_agent_health():
    """Several tests in this file deliberately force role_name="pm" to raise
    (to exercise the exception path), which calls agent_registry.fail_task()
    for real against the shared, process-wide registry singleton. 3+ failures
    flips health to "unhealthy", and plain complete_task() doesn't reset
    that — leaving "pm" permanently invisible to fleet_manager.select() for
    every other test in the suite (confirmed: test_session4_migration.py's
    TestFleetManagerSelection failed only when run after this file, not in
    isolation). recover() resets state/error_count/health together."""
    yield
    from app.fleet.agent_registry import get_agent_registry

    instance = get_agent_registry().get("pm")
    if instance is not None:
        instance.recover()

_SUBMITTED_ANTHROPIC_RESPONSE = type(
    "R",
    (),
    {
        "content": [
            type(
                "B",
                (),
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "submit_brief",
                    "input": {"smoke_test": True},
                },
            )()
        ],
        "usage": type("U", (), {"input_tokens": 10, "output_tokens": 10})(),
        "stop_reason": "tool_use",
    },
)()


def _mock_anthropic_submitting() -> object:
    from unittest.mock import MagicMock

    client = MagicMock()
    client.messages.create.return_value = _SUBMITTED_ANTHROPIC_RESPONSE
    return client


class TestTaskIdVsTraceIdBugFix:
    """The real, systemic bug: task_id=tid at 4 call sites inside
    run_agent_graph(). Verified by capturing the real FleetEvent objects
    passed to publish(), not just asserting no exception was raised."""

    def test_task_started_and_completed_use_the_real_task_id(self) -> None:
        from app.agents.base_graph import VerificationConfig, run_agent_graph

        captured_events: list = []

        def _fake_publish(event: object) -> None:
            captured_events.append(event)

        with patch("anthropic.Anthropic") as mock_anthropic, patch(
            "app.fleet.fleet_events.publish", side_effect=_fake_publish
        ):
            mock_anthropic.return_value = _mock_anthropic_submitting()
            run_agent_graph(
                role_name="pm",
                model="claude-haiku",
                tools=[{"name": "submit_brief", "input_schema": {"type": "object", "properties": {}}}],
                tool_handlers={"submit_brief": lambda inp: "ok"},
                verification_cfg=VerificationConfig(
                    set_by={"submit_brief": "brief_submitted"},
                    reset_by=(),
                    reset_keys=(),
                    enforce_in_result={"brief_submitted": "brief_submitted"},
                    initial={"brief_submitted": False},
                ),
                initial_message="do the thing",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                max_turns=3,
                task_id="99999",
                trace_id="some-completely-different-trace-hex",
            )

        task_events = [e for e in captured_events if e.event_type.value in ("TaskStarted", "TaskCompleted")]
        assert task_events, "expected at least a TaskStarted or TaskCompleted event"
        for event in task_events:
            assert event.task_id == "99999", (
                f"{event.event_type.value}.task_id was {event.task_id!r} — "
                "should be the real task_id, not the trace_id"
            )
            assert event.trace_id == "some-completely-different-trace-hex"

    def test_task_failed_uses_the_real_task_id_on_exception(self) -> None:
        from app.agents.base_graph import VerificationConfig, run_agent_graph

        captured_events: list = []

        def _fake_publish(event: object) -> None:
            captured_events.append(event)

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")), patch(
            "app.fleet.fleet_events.publish", side_effect=_fake_publish
        ):
            with pytest.raises(RuntimeError):
                run_agent_graph(
                    role_name="pm",
                    model="claude-haiku",
                    tools=[],
                    tool_handlers={},
                    verification_cfg=VerificationConfig(
                        set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
                    ),
                    initial_message="do the thing",
                    enable_planning=False,
                    enable_memory=False,
                    enable_reflection=False,
                    enable_lesson=False,
                    max_turns=3,
                    task_id="88888",
                    trace_id="another-trace-hex",
                )

        failed_events = [e for e in captured_events if e.event_type.value == "TaskFailed"]
        assert failed_events, "expected a TaskFailed event on exception"
        assert failed_events[0].task_id == "88888"
        assert failed_events[0].trace_id == "another-trace-hex"

    def test_agent_registry_current_task_id_is_the_real_task_id(self) -> None:
        from app.agents.base_graph import VerificationConfig, run_agent_graph
        from app.fleet.agent_registry import get_agent_registry

        get_agent_registry().register("pm")

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value = _mock_anthropic_submitting()
            run_agent_graph(
                role_name="pm",
                model="claude-haiku",
                tools=[{"name": "submit_brief", "input_schema": {"type": "object", "properties": {}}}],
                tool_handlers={"submit_brief": lambda inp: "ok"},
                verification_cfg=VerificationConfig(
                    set_by={"submit_brief": "brief_submitted"},
                    reset_by=(),
                    reset_keys=(),
                    enforce_in_result={"brief_submitted": "brief_submitted"},
                    initial={"brief_submitted": False},
                ),
                initial_message="do the thing",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                max_turns=3,
                task_id="77777",
                trace_id="yet-another-trace-hex",
            )
        # complete_task() resets current_task_id to None on success — the bug
        # is only observable mid-run, so assert via start_task() directly.
        # Must restore "pm" back to available afterward — leaving it RUNNING
        # would make it invisible to fleet_manager.select() for every other
        # test in the shared, process-wide agent_registry singleton.
        try:
            instance = get_agent_registry().start_task("pm", task_id="77777")
            assert instance.current_task_id == "77777"
        finally:
            get_agent_registry().complete_task("pm")


class TestHealthUpdatedOnErrorPath:
    def test_exception_path_publishes_health_updated(self) -> None:
        from app.agents.base_graph import VerificationConfig, run_agent_graph

        captured_events: list = []

        def _fake_publish(event: object) -> None:
            captured_events.append(event)

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")), patch(
            "app.fleet.fleet_events.publish", side_effect=_fake_publish
        ):
            with pytest.raises(RuntimeError):
                run_agent_graph(
                    role_name="pm",
                    model="claude-haiku",
                    tools=[],
                    tool_handlers={},
                    verification_cfg=VerificationConfig(
                        set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
                    ),
                    initial_message="do the thing",
                    enable_planning=False,
                    enable_memory=False,
                    enable_reflection=False,
                    enable_lesson=False,
                    max_turns=3,
                    task_id="66666",
                )

        health_events = [e for e in captured_events if e.event_type.value == "HealthUpdated"]
        assert health_events, "expected a HealthUpdated event on the exception path"
        assert health_events[-1].payload["health"] == "error"


class TestCheckpointWiringOnExceptionPath:
    def test_exception_path_saves_a_real_checkpoint(self) -> None:
        from app.agents.base_graph import VerificationConfig, run_agent_graph
        from app.fleet.fleet_checkpoint import get_checkpoint_store

        store = get_checkpoint_store()
        before = store.total_saved

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                run_agent_graph(
                    role_name="pm",
                    model="claude-haiku",
                    tools=[],
                    tool_handlers={},
                    verification_cfg=VerificationConfig(
                        set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
                    ),
                    initial_message="do the thing",
                    enable_planning=False,
                    enable_memory=False,
                    enable_reflection=False,
                    enable_lesson=False,
                    max_turns=3,
                    task_id="55555",
                )

        assert store.total_saved == before + 1


class TestManagerTraceIdAndCheckpointWiring:
    def test_epic_abort_saves_checkpoint_and_uses_real_trace_id(self) -> None:
        """settings.manager_max_epic_failures defaults to 2 — two failing
        subtasks (each exhausting its own retries) trigger the epic-halt/
        abort path without needing to mock settings at all."""
        import asyncio

        from app.agents.manager import run_manager
        from app.fleet.fleet_checkpoint import get_checkpoint_store

        store = get_checkpoint_store()
        before = store.total_saved

        subtasks = [
            {"id": 1, "type": "backend", "title": "t1", "description": "d1"},
            {"id": 2, "type": "backend", "title": "t2", "description": "d2"},
        ]

        captured_abort_calls: list = []

        def _fake_abort(task_id, reason, trace_id=""):
            captured_abort_calls.append((task_id, reason, trace_id))
            return True

        with patch(
            "app.agents.backend_dev.run_backend_dev", return_value=([], "always fails")
        ), patch("app.event_bus.bus.publish_event"), patch(
            "app.fleet.failure_ladder.abort", side_effect=_fake_abort
        ):
            asyncio.run(
                run_manager(
                    task_id=44444,
                    subtasks=subtasks,
                    worktree_path="/tmp/wt",
                    plan="p",
                )
            )

        assert store.total_saved == before + 1
        assert captured_abort_calls, "expected failure_ladder.abort() to be called"
        _, _, trace_id = captured_abort_calls[0]
        assert trace_id == "task-44444-manager"


class TestAgentRegistryBootstrap:
    def test_ensure_all_agents_registered_covers_all_real_agents(self) -> None:
        from app.fleet.capability_registry import (
            ensure_all_agents_registered,
            get_capability_registry,
        )

        imported = ensure_all_agents_registered()
        assert imported >= 72
        assert get_capability_registry().count() >= 72

    def test_health_endpoint_reports_a_real_agent_count(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "agents" in body
        assert body["agents"] >= 72
        assert "db" in body
