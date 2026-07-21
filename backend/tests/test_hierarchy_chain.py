"""Day 12 Part 4 — Hierarchy Chain Verification.

The plan's chain description (Executive -> fleet_manager selects agent ->
capability_registry lookup -> knowledge_graph context -> agent_bus publishes
TaskCreated -> agent runs -> tool_layer executes -> verification_layer
checks -> reflection_node runs -> lesson_node writes to learning_layer ->
AgentResult returned) does not correspond to a single call chain in this
codebase — confirmed by reading app/pipeline/graph.py, app/agents/manager.py,
and app/fleet/fleet_manager.py in full during Day 12 planning. There are two
real, separate integration points:

1. run_manager()'s subtask dispatch loop (Day 12 Part 4 added the actual
   fleet_manager.select() + agent_bus publish(task_created(...)) calls here —
   previously these modules existed, were unit-tested in isolation, and every
   agent self-registered into them via _register(), but nothing in the live
   task-flow ever called them).
2. run_agent_graph()'s own node graph (tool_layer=execute_tools,
   verification_layer=VerificationConfig/state["verification"],
   reflection_node, and lesson_node=_extract_and_store_lesson -> LessonStore).

"knowledge_graph" does not exist as a module anywhere in this codebase
(verified by search) — the plan's vocabulary there is aspirational, so this
test does not assert anything about it.

This test verifies each of the 6 real, checkable chain steps against the
correct one of those two integration points, rather than pretending they're
one literal call chain.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import app.agents.backend_dev  # noqa: F401 — import triggers _register() into capability_registry
from app.fleet.capability_registry import get_capability_registry
from app.fleet.fleet_events import get_fleet_bus


class _HierarchyChainLLM:
    """Distinguish planner / reflection / lesson-extraction / main-turn calls
    by their distinctive prompt text, so each gets a response its own
    try/except-guarded JSON parsing actually expects — unlike the Part 1
    smoke test's generic mock, this one must satisfy lesson extraction's
    real "lesson" field for LessonStore.add() to actually fire. The first
    main-turn call gets do_thing (so verification_layer/tool_layer actually
    exercise a real tool), every subsequent main-turn call gets submit —
    both tools are present on every call, so this can't be routed by tools
    list alone the way Day 10's single-tool tests could."""

    def __init__(self) -> None:
        self.main_turn_calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Extract a reusable lesson" in last_text:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"lesson": "always validate boundary inputs", "pattern": "input validation", '
                        '"category": "general", "reusable": true}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=20, output_tokens=15),
            )

        if "Review what the tools just produced" in last_text:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"satisfied": true}')],
                usage=SimpleNamespace(input_tokens=15, output_tokens=10),
            )

        tools = kwargs.get("tools") or []
        has_do_thing = any(t.get("name") == "do_thing" for t in tools)
        has_submit = any(str(t.get("name", "")).startswith("submit_") for t in tools)

        if has_do_thing and has_submit:
            self.main_turn_calls += 1
            if self.main_turn_calls == 1:
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use", id="tu_do", name="do_thing", input={}
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=30, output_tokens=10),
                )
            submit_tool = next(
                t for t in tools if str(t.get("name", "")).startswith("submit_")
            )
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu_chain",
                        name=submit_tool["name"],
                        input={"summary": "done"},
                    )
                ],
                usage=SimpleNamespace(input_tokens=50, output_tokens=20),
            )

        # planner_node's two calls, and anything else — safe fallback both nodes tolerate
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_step1_and_step2_fleet_manager_selects_via_capability_registry() -> None:
    """Step 1 (fleet_manager selects agent) and Step 2 (capability_registry
    lookup returned a spec) — both real, both exercised together since
    FleetManager.select() itself calls capability_registry internally."""
    from app.fleet.fleet_manager import get_fleet_manager

    assert (
        get_capability_registry().get("backend_dev") is not None
    ), "backend_dev must be registered in capability_registry for this chain step to be real"

    plan = get_fleet_manager().select(required_capability="backend_development")
    assert (
        plan is not None
    ), "fleet_manager.select() found no agent for backend_development"
    assert plan.agent_name == "backend_dev"
    assert plan.capability is get_capability_registry().get("backend_dev")


def test_step3_agent_bus_publishes_task_created_from_run_manager() -> None:
    """Step 3 (agent_bus publishes TaskCreated) — verified via run_manager()'s
    own Part 4 wiring, using a FleetBus subscriber to observe the real publish
    (not just asserting a mock was called), since get_fleet_bus() is the real
    process-wide bus run_manager() publishes to."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.fleet.fleet_events import FleetEventType

    captured: list[Any] = []
    bus = get_fleet_bus()
    original_publish = bus.publish

    def _capturing_publish(event: Any) -> None:
        captured.append(event)
        original_publish(event)

    with patch.object(bus, "publish", side_effect=_capturing_publish), patch(
        "app.agents.backend_dev.run_backend_dev"
    ) as mock_backend_dev, patch("app.agents.qa.run_qa") as mock_qa, patch(
        "app.agents.reviewer.run_reviewer"
    ) as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value=""
    ):
        mock_backend_dev.return_value = (["app/api/hello.py"], None)
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        asyncio.run(
            run_manager(
                task_id=999_201,
                subtasks=[
                    {
                        "id": 1,
                        "type": "backend",
                        "title": "chain test subtask",
                        "description": "...",
                    }
                ],
                worktree_path="/tmp/does-not-need-to-exist",
                plan="plan",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    task_created_events = [
        e for e in captured if e.event_type == FleetEventType.TASK_CREATED
    ]
    assert (
        len(task_created_events) >= 1
    ), "run_manager() did not publish a real TaskCreated event"
    assert task_created_events[0].payload.get("title") == "chain test subtask"


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("anthropic.Anthropic")
def test_steps_4_5_6_verification_reflection_lesson_and_result(
    mock_anthropic_cls: Any, _load_role: Any
) -> None:
    """Step 4 (reflection_node ran with a non-empty verification dict already
    populated by tool_layer/execute_tools), Step 5 (lesson_node wrote to
    LessonStore, the learning_layer), Step 6 (AgentResult/final_state.result
    is non-empty) — all real inside run_agent_graph()'s own node graph."""
    from app.agents.base_graph import (
        VerificationConfig,
        get_lesson_store,
        run_agent_graph,
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _HierarchyChainLLM()
    mock_anthropic_cls.return_value = mock_client

    lesson_store = get_lesson_store()
    lessons_before = lesson_store.total

    do_thing_tool = {
        "name": "do_thing",
        "description": "Do a thing",
        "input_schema": {"type": "object", "properties": {}},
    }
    submit_tool = {
        "name": "submit_result",
        "description": "Submit",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
        },
    }

    def _do_thing_handler(inp: dict[str, Any]) -> str:
        return "did the thing"

    def _submit_handler(inp: dict[str, Any]) -> str:
        return "ok"

    final_state = run_agent_graph(
        role_name="hierarchy_chain_test_agent",
        model="claude-haiku-4-5-20251001",
        tools=[do_thing_tool, submit_tool],
        tool_handlers={"do_thing": _do_thing_handler, "submit_result": _submit_handler},
        verification_cfg=VerificationConfig(
            initial={},
            set_by={"do_thing": "did_thing"},
            reset_by=(),
            reset_keys=(),
            enforce_in_result={"did_thing": "did_thing"},
        ),
        initial_message="do a task",
        enable_planning=False,
        enable_memory=False,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=6,
    )

    # Step 4: verification_layer populated a non-empty dict before reflection ran.
    assert final_state["verification"].get("did_thing") is True

    reflection_calls = [
        c
        for c in mock_client.messages.create.call_args_list
        if "Review what the tools just produced"
        in str((c.kwargs.get("messages") or [{}])[-1].get("content", ""))
    ]
    assert len(reflection_calls) >= 1, "reflection_node never actually called the LLM"

    # Step 5: lesson_node (_extract_and_store_lesson) wrote to the learning layer.
    assert (
        lesson_store.total > lessons_before
    ), "no lesson was stored after the run completed"

    # Step 6: AgentResult (final_state["result"]) is non-empty.
    assert final_state.get("submitted") is True
    assert final_state.get("result")
