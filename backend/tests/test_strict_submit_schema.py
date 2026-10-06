"""Strict submit schema for code/plan submissions (PENDING L1, owner decision
2026-10-06). Live runs showed 1 schema miss in ~25 submissions; for submit
tools whose output feeds code or plans the submission is now rejected before
its handler runs and the agent resubmits. Report submits stay soft."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.agents.base_graph import VerificationConfig, run_agent_graph

_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "risk": {"type": "string"}},
    "required": ["summary", "risk"],
}


def _reply(name: str, inp: dict[str, Any], n: int) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=f"tu{n}", name=name, input=inp)],
        usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        stop_reason="tool_use",
    )


def _run(
    tool: str, replies: list[dict[str, Any]]
) -> tuple[Any, list[dict[str, Any]], list[Any]]:
    calls: list[dict[str, Any]] = []
    handled: list[Any] = []

    def fake(**kw: Any) -> Any:
        calls.append(kw)
        return _reply(tool, replies[min(len(calls), len(replies)) - 1], len(calls))

    with patch("app.agents.base_graph.load_role", return_value="# Test\n"), patch(
        "anthropic.Anthropic"
    ) as cls:
        cls.return_value.messages.create.side_effect = fake
        state = run_agent_graph(
            role_name="t",
            model="claude-haiku-4-5-20251001",
            tools=[{"name": tool, "description": "", "input_schema": _SCHEMA}],
            tool_handlers={tool: lambda i: handled.append(i) or "ok"},
            verification_cfg=VerificationConfig(),
            initial_message="do it",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_run_tracking=False,
            max_turns=5,
        )
    return state, calls, handled


def test_invalid_patch_submission_is_rejected_before_its_handler_then_resubmitted() -> (
    None
):
    state, calls, handled = _run(
        "submit_patch",
        [{"summary": "missing risk"}, {"summary": "fixed", "risk": "low"}],
    )
    assert state["submitted"] is True
    assert len(calls) == 2, "the model must get a second chance"
    assert handled == [
        {"summary": "fixed", "risk": "low"}
    ], "invalid patch must never be applied"
    rejection = str(calls[1]["messages"][-1]["content"])
    assert "submit_patch rejected" in rejection and "risk" in rejection
    assert "_validation_warning" not in state["result"]


def test_report_submission_stays_soft() -> None:
    state, calls, handled = _run("submit_report", [{"summary": "missing risk"}])
    assert state["submitted"] is True
    assert len(calls) == 1
    assert handled == [{"summary": "missing risk"}]
    assert "risk" in state["result"]["_validation_warning"]
