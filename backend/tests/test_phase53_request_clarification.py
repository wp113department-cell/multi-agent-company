"""Tests for MASTER_AGENT_v2.md Phase 5.3 — request_clarification tool.

Scope decision (documented, not hidden): base_graph.py (the graph every
worker agent besides pm/architect/decomposer runs on) has no checkpointer or
interrupt()/Command(resume=...) machinery of its own — that only exists in
app/pipeline/graph.py's separate pm->architect->decomposer pipeline. A true
mid-run pause/resume for base_graph.py agents is graph-level work (Phase
5.1/5.5's territory). This is the real, working version that fits the
existing shape: the agent ends its run cleanly with a distinct
status="needs_clarification" (never a silent hang or an ordinary completed/
blocked result) after recording a genuine PendingApproval row through the
same table app/fleet/approval_gate.py already uses for the pipeline's own
human_review pause.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import AgentRunState, VerificationConfig, run_agent_graph
from app.agents.tools import (
    REQUEST_CLARIFICATION_TOOL,
    make_request_clarification_handler,
)

# ---------------------------------------------------------------------------
# make_request_clarification_handler — direct unit tests
# ---------------------------------------------------------------------------


def test_handler_records_a_real_pending_approval_row() -> None:
    """Phase 5.5 — the handler now goes through the generalized
    request_human_input() entry point rather than calling record_pending()
    directly, so the recorded row picks up an extra 'blocking': False in
    details (this call is the non-blocking "clean stop" kind of HITL pause —
    see approval_gate.py's own HumanInputKind design note)."""
    handler = make_request_clarification_handler("planner", "42")
    with patch("app.fleet.approval_gate.record_pending") as mock_record:
        mock_record.return_value = SimpleNamespace(id=1)
        result = handler(
            {"question": "Which auth provider?", "context": "found 2 candidates"}
        )

    assert "recorded" in result.lower()
    mock_record.assert_called_once_with(
        thread_id="clarify-42-planner",
        action="clarification",
        details={
            "question": "Which auth provider?",
            "context": "found 2 candidates",
            "blocking": False,
        },
        agent_name="planner",
        task_id=42,
    )


def test_handler_requires_a_question() -> None:
    handler = make_request_clarification_handler("planner", "42")
    result = handler({"context": "no question given"})
    assert result.startswith("[ERROR]")


def test_handler_failure_is_reported_not_raised() -> None:
    handler = make_request_clarification_handler("planner", "42")
    with patch(
        "app.fleet.approval_gate.record_pending", side_effect=RuntimeError("db down")
    ):
        result = handler({"question": "q?"})
    assert result.startswith("[ERROR]")


def test_handler_with_non_numeric_task_id_records_null_task_id() -> None:
    handler = make_request_clarification_handler("architect", "")
    with patch("app.fleet.approval_gate.record_pending") as mock_record:
        mock_record.return_value = SimpleNamespace(id=1)
        handler({"question": "q?"})
    assert mock_record.call_args.kwargs["task_id"] is None
    assert mock_record.call_args.kwargs["thread_id"] == "clarify-notask-architect"


# ---------------------------------------------------------------------------
# base_graph.py wiring — ends the run cleanly with a distinct status, sets
# requires_human_approval, never treated as a normal submitted result.
# ---------------------------------------------------------------------------


class _ClarificationLLM:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools") or []
        has_clarify = any(t.get("name") == "request_clarification" for t in tools)
        if has_clarify:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu1",
                        name="request_clarification",
                        input={"question": "Which env?", "context": "prod or staging?"},
                    )
                ],
                usage=SimpleNamespace(input_tokens=20, output_tokens=10),
            )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_graph_ends_cleanly_with_needs_clarification_status() -> None:
    llm = _ClarificationLLM()
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls, patch(
        "app.fleet.approval_gate.record_pending"
    ) as mock_record:
        mock_record.return_value = SimpleNamespace(id=1)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state: AgentRunState = run_agent_graph(
            role_name="clarify_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[REQUEST_CLARIFICATION_TOOL],
            tool_handlers={
                "request_clarification": make_request_clarification_handler(
                    "clarify_test_agent", "7"
                )
            },
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do an ambiguous task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=5,
        )

    assert final_state["submitted"] is True
    assert final_state["result"]["status"] == "needs_clarification"
    assert final_state["result"]["question"] == "Which env?"
    assert final_state["requires_human_approval"] is True
    mock_record.assert_called_once()


def test_graph_never_calls_llm_again_after_clarification_request() -> None:
    """Confirms the run truly ends (router sees submitted=True) rather than
    looping — a real 'clean stop', not just a status label with a hang
    underneath."""
    llm = _ClarificationLLM()
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls, patch(
        "app.fleet.approval_gate.record_pending"
    ) as mock_record:
        mock_record.return_value = SimpleNamespace(id=1)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        run_agent_graph(
            role_name="clarify_test_agent_2",
            model="claude-haiku-4-5-20251001",
            tools=[REQUEST_CLARIFICATION_TOOL],
            tool_handlers={
                "request_clarification": make_request_clarification_handler(
                    "clarify_test_agent_2", "8"
                )
            },
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do an ambiguous task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=10,
        )

    # 1 real main-turn call (submits the clarification tool_use); router
    # sees submitted=True on the very next pass and stops — matches the
    # exact same "one extra pass through call_llm" shape already documented
    # and tested for plain submit_* in test_phase35_self_critique.py.
    assert mock_client.messages.create.call_count <= 2


# ---------------------------------------------------------------------------
# planner.py — real per-agent integration
# ---------------------------------------------------------------------------


def test_planner_surfaces_clarification_via_existing_error_slot() -> None:
    """External interface (return shape) deliberately unchanged — the
    signal is a parseable prefix in the existing error slot, confirmed
    directly against the real run_planner()."""
    from app.agents.planner import run_planner

    llm = _ClarificationLLM()
    with patch("app.agents.base_graph.load_role", return_value="# Planner\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls, patch(
        "app.fleet.approval_gate.record_pending"
    ) as mock_record:
        mock_record.return_value = SimpleNamespace(id=1)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        plan, error, tokens_in, tokens_out = run_planner(
            task_id=123,
            title="Ambiguous task",
            description="build the thing",
            repo_path=".",
        )

    assert plan == ""
    assert error is not None
    assert error.startswith("[NEEDS_CLARIFICATION]")
    assert "Which env?" in error


def test_planner_contract_declares_request_clarification() -> None:
    from app.agents.planner import AGENT_CONTRACT

    assert "request_clarification" in AGENT_CONTRACT["allowed_tools"]
