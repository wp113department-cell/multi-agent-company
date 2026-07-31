"""Gap-closure Stage 1.6 (answers.md) — Requirement compliance & clarification.

Proves the plan's own acceptance criterion: "a scripted conflicting-tech-
constraint prompt triggers request_clarification, not silent substitution."

The Hard-Constraint Conflict Rule added to roles/_GLOBAL_STANDARDS.md (and
roles/chat.md's own Escalation section) is prompt guidance — a real model's
adherence to it can't be forced by a unit test (this codebase's own
established convention: prompt behavior is reviewed, not unit-tested). What
IS code, and what this test proves end to end through the real compiled
graph: when a worker agent (scripted here to simulate having followed the
new rule) encounters a task with two conflicting hard constraints and calls
request_clarification instead of silently picking one, the real mechanism
(app/agents/tools.py::REQUEST_CLARIFICATION_TOOL,
make_request_clarification_handler, base_graph.py's execute_tools) actually
carries that through: a real PendingApproval row is recorded with BOTH
conflicting constraints named in the question/context (not a vague "is this
ok?"), and the run ends cleanly with needs_clarification — never a
submitted result that silently chose one side.

Mirrors tests/test_phase53_request_clarification.py's own established
scripted-LLM pattern; this file adds the specific conflicting-constraint
scenario that file's own generic "ambiguous task" LLM doesn't cover.
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

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "database": {"type": "string"}},
    },
}


class _ConflictingConstraintLLM:
    """Simulates a model that correctly followed the Hard-Constraint
    Conflict Rule: given a task stating both 'use PostgreSQL' and 'use
    only SQLite, no external services', it calls request_clarification
    naming BOTH constraints and why they conflict — the exact 'state the
    conflict factually' behavior the rule requires — instead of silently
    picking one and calling submit_result."""

    def __init__(self) -> None:
        self.called_submit = False
        self.called_clarify = False

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools") or []
        has_clarify = any(t.get("name") == "request_clarification" for t in tools)
        if has_clarify:
            self.called_clarify = True
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu1",
                        name="request_clarification",
                        input={
                            "question": (
                                "The task asks for PostgreSQL but also says "
                                "'no external services, SQLite only' — these "
                                "conflict. Which should stand?"
                            ),
                            "context": (
                                "Repo evidence: app/config.py's database_url "
                                "already assumes Postgres+asyncpg; no SQLite "
                                "driver is installed."
                            ),
                        },
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=15),
            )
        # If this branch is ever reached, the scripted model silently picked
        # a side instead of flagging the conflict — exactly the failure
        # mode this rule exists to prevent. Tracked so the test can assert
        # it never happens.
        self.called_submit = True
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="tu_bad",
                    name="submit_result",
                    input={"summary": "used postgres", "database": "postgres"},
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_conflicting_hard_constraints_trigger_request_clarification_not_silent_choice() -> (
    None
):
    llm = _ConflictingConstraintLLM()
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
            role_name="hard_constraint_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[REQUEST_CLARIFICATION_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "request_clarification": make_request_clarification_handler(
                    "hard_constraint_test_agent", "99"
                ),
                "submit_result": lambda inp: "ok",
            },
            verification_cfg=VerificationConfig(),
            initial_message=(
                "Set up the database. Use PostgreSQL. Also: no external "
                "services, SQLite only."
            ),
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=5,
        )

    # The model must have actually called request_clarification, not
    # silently resolved the conflict itself.
    assert llm.called_clarify is True
    assert llm.called_submit is False

    assert final_state["submitted"] is True
    assert final_state["result"]["status"] == "needs_clarification"
    # Both conflicting constraints are named in the recorded question — a
    # real, specific conflict, not a vague "is this ok?" (which the tool's
    # own description explicitly forbids).
    question = final_state["result"]["question"]
    assert "PostgreSQL" in question
    assert "SQLite" in question
    assert final_state["requires_human_approval"] is True

    # A real PendingApproval row was recorded — this is a genuine pause,
    # not just an in-memory status flag nobody durably tracks.
    mock_record.assert_called_once()
    recorded_details = mock_record.call_args.kwargs["details"]
    assert "PostgreSQL" in recorded_details["question"]
