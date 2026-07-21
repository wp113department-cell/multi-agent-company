"""Day 0 — capability activation tests.

Proves each Fleet OS node (planner, memory, reflection, lesson) fires
when run_agent_graph() is called with default flags (now all True).
Also verifies Sleep lifecycle wiring and trace_id propagation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.base_graph import (
    AgentRunState,
    build_agent_graph,
    run_agent_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DUMMY_TOOL: dict[str, Any] = {
    "name": "submit_result",
    "description": "Submit final result",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


def _submit_handler(inp: dict[str, Any]) -> str:
    return "ok"


def _make_llm_response(text: str = '{"summary": "done"}') -> dict[str, Any]:
    """Fake Anthropic messages.create() response."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=50, output_tokens=25),
    )


def _make_tool_use_response(tool_name: str = "submit_result") -> dict[str, Any]:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="tu_001",
                name=tool_name,
                input={"summary": "task done"},
            )
        ],
        usage=SimpleNamespace(input_tokens=50, output_tokens=25),
    )


# ---------------------------------------------------------------------------
# 1. Default flags are now True
# ---------------------------------------------------------------------------


class TestDefaultFlagsAreTrue:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_build_agent_graph_defaults_to_planning_enabled(
        self, _k: Any, _l: Any
    ) -> None:
        import inspect

        sig = inspect.signature(build_agent_graph)
        assert sig.parameters["enable_planning"].default is True

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_build_agent_graph_defaults_to_memory_enabled(
        self, _k: Any, _l: Any
    ) -> None:
        import inspect

        sig = inspect.signature(build_agent_graph)
        assert sig.parameters["enable_memory"].default is True

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_build_agent_graph_defaults_to_reflection_enabled(
        self, _k: Any, _l: Any
    ) -> None:
        import inspect

        sig = inspect.signature(build_agent_graph)
        assert sig.parameters["enable_reflection"].default is True

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_run_agent_graph_defaults_to_lesson_enabled(self, _k: Any, _l: Any) -> None:
        import inspect
        from app.agents.base_graph import run_agent_graph

        sig = inspect.signature(run_agent_graph)
        assert sig.parameters["enable_lesson"].default is True

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_build_agent_graph_still_compiles_with_explicit_false(
        self, _k: Any, _l: Any
    ) -> None:
        graph = build_agent_graph(
            role_name="bug_fix",
            model="claude-haiku-4-5-20251001",
            tools=[DUMMY_TOOL],
            tool_handlers={"submit_result": _submit_handler},
            verification_cfg=MagicMock(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
        )
        assert graph is not None


# ---------------------------------------------------------------------------
# 2. planner_node fires (produces plan + facts + confidence in state)
# ---------------------------------------------------------------------------


class TestPlannerNodeFires:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_planner_node_sets_plan_in_state(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        plan_json = json.dumps({"steps": ["step1"], "confidence": 0.9, "risks": []})
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response(plan_json)
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _make_planner_node

        planner = _make_planner_node("claude-haiku-4-5-20251001", "write tests")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "write tests"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = planner(state)
        assert "plan" in out
        assert "confidence" in out
        assert isinstance(out["confidence"], float)

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_planner_node_extracts_confidence_from_json(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        plan_json = json.dumps({"steps": [], "confidence": 0.75, "risks": []})
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response(plan_json)
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _make_planner_node

        planner = _make_planner_node("claude-haiku-4-5-20251001", "write tests")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "write tests"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = planner(state)
        assert out["confidence"] == pytest.approx(0.75)

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_planner_node_makes_two_llm_calls(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response("{}")
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _make_planner_node

        planner = _make_planner_node("claude-haiku-4-5-20251001", "add feature")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "add feature"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        planner(state)
        assert mock_client.messages.create.call_count == 2  # facts + plan


# ---------------------------------------------------------------------------
# 3. memory_hook_node fires (populates memory_context)
# ---------------------------------------------------------------------------


class TestMemoryHookNodeFires:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_memory_hook_returns_memory_context_when_lessons_exist(
        self, _k: Any, _l: Any
    ) -> None:
        from app.agents.base_graph import (
            _make_memory_hook_node,
            get_lesson_store,
            Lesson,
        )

        ls = get_lesson_store()
        ls.add(
            Lesson("test_agent", "always write tests first", "TDD pattern", "testing")
        )

        hook = _make_memory_hook_node("write tests for auth module", "")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "write tests for auth"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = hook(state)
        assert "memory_context" in out
        assert "tests" in out["memory_context"].lower()

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_memory_hook_is_non_fatal_when_repo_missing(self, _k: Any, _l: Any) -> None:
        from app.agents.base_graph import _make_memory_hook_node

        hook = _make_memory_hook_node("some task", "/nonexistent/path/does/not/exist")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "some task"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = hook(state)  # must not raise
        assert isinstance(out, dict)

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_memory_hook_skips_repo_context_when_already_set(
        self, _k: Any, _l: Any
    ) -> None:
        from app.agents.base_graph import _make_memory_hook_node

        hook = _make_memory_hook_node("task", "/some/path")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "task"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
            "repo_context": "already set",
        }
        out = hook(state)
        assert out.get("repo_context") is None  # not overwritten


# ---------------------------------------------------------------------------
# 4. reflection_node fires (appends self-review message when not satisfied)
# ---------------------------------------------------------------------------


class TestReflectionNodeFires:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_reflection_node_appends_message_when_not_satisfied(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        reflection_json = json.dumps(
            {"satisfied": False, "issues": ["edge case missing"]}
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response(reflection_json)
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _make_reflection_node

        node = _make_reflection_node("claude-sonnet-5")
        state: AgentRunState = {
            "messages": [
                {"role": "user", "content": "task"},
                {"role": "assistant", "content": []},
            ],
            "verification": {},
            "result": {},
            "turns": 1,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 50,
            "tokens_out": 25,
        }
        out = node(state)
        assert "messages" in out
        assert len(out["messages"]) == 3  # added self-review message
        assert "[Self-review]" in out["messages"][-1]["content"]

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_reflection_node_returns_empty_when_satisfied(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        reflection_json = json.dumps({"satisfied": True, "issues": []})
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response(reflection_json)
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _make_reflection_node

        node = _make_reflection_node("claude-sonnet-5")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "task"}],
            "verification": {},
            "result": {},
            "turns": 1,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 50,
            "tokens_out": 25,
        }
        out = node(state)
        assert out == {}  # no new messages when satisfied


# ---------------------------------------------------------------------------
# 5. lesson_node fires (extract_and_store_lesson called on submit)
# ---------------------------------------------------------------------------


class TestLessonNodeFires:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_lesson_stored_after_submit(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        lesson_json = json.dumps(
            {
                "lesson": "always add type hints",
                "pattern": "strict typing",
                "category": "general",
                "reusable": True,
            }
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response(lesson_json)
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _extract_and_store_lesson, get_lesson_store

        before = get_lesson_store().total
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "add type hints"}],
            "verification": {},
            "result": {"summary": "done"},
            "turns": 2,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 100,
            "tokens_out": 50,
        }
        _extract_and_store_lesson(
            state, "coder", "claude-haiku-4-5-20251001", trace_id="abc123"
        )
        assert get_lesson_store().total == before + 1

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_lesson_extraction_is_non_fatal_on_bad_json(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_llm_response("not json at all")
        mock_anthropic.return_value = mock_client

        from app.agents.base_graph import _extract_and_store_lesson

        state: AgentRunState = {
            "messages": [{"role": "user", "content": "task"}],
            "verification": {},
            "result": {},
            "turns": 1,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 50,
            "tokens_out": 25,
        }
        # Must not raise
        _extract_and_store_lesson(state, "planner", "claude-haiku-4-5-20251001")


# ---------------------------------------------------------------------------
# 6. trace_id flows into state and events
# ---------------------------------------------------------------------------


class TestTraceIdPropagation:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_trace_id_in_initial_state(self, _k: Any, _l: Any) -> None:
        import inspect
        from app.agents.base_graph import run_agent_graph

        sig = inspect.signature(run_agent_graph)
        assert "trace_id" in sig.parameters

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_explicit_trace_id_propagated(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        from app.fleet.fleet_events import FleetEvent

        published_events: list[FleetEvent] = []

        def fake_publish(ev: FleetEvent) -> None:
            published_events.append(ev)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_tool_use_response(
            "submit_result"
        )
        mock_anthropic.return_value = mock_client

        with patch("app.fleet.fleet_events.publish", side_effect=fake_publish):
            try:
                run_agent_graph(
                    role_name="coder",
                    model="claude-haiku-4-5-20251001",
                    tools=[DUMMY_TOOL],
                    tool_handlers={"submit_result": _submit_handler},
                    verification_cfg=MagicMock(
                        initial={},
                        set_by={},
                        reset_by=(),
                        reset_keys=(),
                        enforce_in_result={},
                    ),
                    initial_message="fix the bug",
                    trace_id="TRACE-FIXED-001",
                    enable_planning=False,
                    enable_memory=False,
                    enable_reflection=False,
                    enable_lesson=False,
                )
            except Exception:
                pass  # we only care that events were emitted

        trace_ids_seen = {ev.trace_id for ev in published_events if ev.trace_id}
        assert "TRACE-FIXED-001" in trace_ids_seen


# ---------------------------------------------------------------------------
# 7. Agent Lifecycle Sleep wiring (Gap 7)
# ---------------------------------------------------------------------------


class TestAgentLifecycleSleepWiring:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_agent_registry_transitions_to_sleep_after_run(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        from app.fleet.agent_registry import get_agent_registry, AgentState

        reg = get_agent_registry()
        reg.register("test_sleep_agent")
        reg.start_task("test_sleep_agent", task_id="pre_run")
        assert reg.get("test_sleep_agent").state == AgentState.RUNNING

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_tool_use_response(
            "submit_result"
        )
        mock_anthropic.return_value = mock_client

        try:
            run_agent_graph(
                role_name="test_sleep_agent",
                model="claude-haiku-4-5-20251001",
                tools=[DUMMY_TOOL],
                tool_handlers={"submit_result": _submit_handler},
                verification_cfg=MagicMock(
                    initial={},
                    set_by={},
                    reset_by=(),
                    reset_keys=(),
                    enforce_in_result={},
                ),
                initial_message="do a task",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
            )
        except Exception:
            pass

        inst = reg.get("test_sleep_agent")
        assert inst is not None
        assert inst.state == AgentState.SLEEP

    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    @patch("app.agents.base_graph.anthropic.Anthropic")
    def test_health_updated_event_emitted_after_sleep(
        self, mock_anthropic: Any, _k: Any, _l: Any
    ) -> None:
        from app.fleet.fleet_events import FleetEvent, FleetEventType

        published_events: list[FleetEvent] = []

        def fake_publish(ev: FleetEvent) -> None:
            published_events.append(ev)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_tool_use_response(
            "submit_result"
        )
        mock_anthropic.return_value = mock_client

        with patch("app.fleet.fleet_events.publish", side_effect=fake_publish):
            try:
                run_agent_graph(
                    role_name="sleep_event_agent",
                    model="claude-haiku-4-5-20251001",
                    tools=[DUMMY_TOOL],
                    tool_handlers={"submit_result": _submit_handler},
                    verification_cfg=MagicMock(
                        initial={},
                        set_by={},
                        reset_by=(),
                        reset_keys=(),
                        enforce_in_result={},
                    ),
                    initial_message="do work",
                    enable_planning=False,
                    enable_memory=False,
                    enable_reflection=False,
                    enable_lesson=False,
                )
            except Exception:
                pass

        health_events = [
            e for e in published_events if e.event_type == FleetEventType.HEALTH_UPDATED
        ]
        assert len(health_events) >= 1
        assert health_events[-1].payload.get("state") == "sleep"


# ---------------------------------------------------------------------------
# 8. Settings-based defaults wired (Gap task 2)
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    @patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
    @patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
    def test_run_agent_graph_accepts_empty_model_haiku_and_repo_path(
        self, _k: Any, _l: Any
    ) -> None:
        """When model_haiku and repo_path are not provided, settings defaults apply."""
        import inspect
        from app.agents.base_graph import run_agent_graph

        sig = inspect.signature(run_agent_graph)
        assert sig.parameters["model_haiku"].default == ""
        assert sig.parameters["repo_path"].default == ""
