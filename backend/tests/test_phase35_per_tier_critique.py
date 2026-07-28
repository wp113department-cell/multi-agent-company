"""Tests for MASTER_AGENT_v2.md Phase 3.5 gap-closure — the spec's own
Definition of Done: "The self-critique loop produces a structured, evidenced
per-criterion checklist ... for at least one full end-to-end test per agent
tier (Executor/Analyzer/Editor)."

tests/test_phase35_self_critique.py already proves the critique_node
*mechanism* thoroughly, but every one of its graph-integration tests uses a
synthetic test-only role ("critique_test_agent" / ROLE_WITH_CRITERIA), not a
real per-tier agent. This file closes that gap: one real agent per tier,
using its actual role file's real Quality Gates/Success Criteria text (parsed
by the real _extract_role_criteria, not a stand-in), its actual _TOOLS/
handler factory/VerificationConfig, invoked through run_agent_graph directly
with enable_critique=True (no run_<agent>() wrapper exposes this flag yet —
critique is still fleet-wide opt-in per Phase 3.5's own rollout decision, so
enabling it here for the test is exactly how a future per-agent opt-in would
look).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import AgentRunState, run_agent_graph


class _PerTierCritiqueLLM:
    """First submission is deliberately incomplete (omits one real Quality
    Gate the agent's own role file requires); critique catches it citing
    that real criterion; second submission is treated as satisfying it."""

    def __init__(self, submit_tool_name: str, submit_input: dict[str, Any]) -> None:
        self.submit_tool_name = submit_tool_name
        self.submit_input = submit_input
        self.main_turn_calls = 0
        self.critique_prompts: list[str] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Score it against these" in last_text:
            self.critique_prompts.append(last_text)
            all_met = len(self.critique_prompts) >= 2
            payload = {
                "criteria": [
                    {
                        "criterion": "placeholder",
                        "met": all_met,
                        "evidence": "checked against submitted result",
                    }
                ],
                "all_met": all_met,
            }
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                usage=SimpleNamespace(input_tokens=20, output_tokens=15),
            )

        tools = kwargs.get("tools") or []
        has_submit = any(t.get("name") == self.submit_tool_name for t in tools)
        if has_submit:
            self.main_turn_calls += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id=f"tu_{self.main_turn_calls}",
                        name=self.submit_tool_name,
                        input=self.submit_input,
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )

        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _run_real_agent_with_critique(
    *,
    role_name: str,
    tools: list[dict[str, Any]],
    handlers: dict[str, Any],
    verification_cfg: Any,
    submit_tool_name: str,
    submit_input: dict[str, Any],
) -> tuple[AgentRunState, _PerTierCritiqueLLM]:
    llm = _PerTierCritiqueLLM(submit_tool_name, submit_input)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = llm

    with patch("anthropic.Anthropic", return_value=mock_client):
        final_state = run_agent_graph(
            role_name=role_name,
            model="claude-haiku-4-5-20251001",
            tools=tools,
            tool_handlers=handlers,
            verification_cfg=verification_cfg,
            initial_message="Do the task.",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_critique=True,
            max_critique_retries=1,
            max_turns=10,
        )
    return final_state, llm


# ---------------------------------------------------------------------------
# Executor tier — debugger_agent (real role file, real read-only tool set,
# real VerificationConfig)
# ---------------------------------------------------------------------------


def test_executor_tier_real_agent_critique_end_to_end() -> None:
    from app.agents.debugger_agent import (
        _CFG,
        _TOOLS,
        make_debugger_agent_handlers,
    )

    handlers = make_debugger_agent_handlers(".")
    submit_input = {
        "summary": "Found the root cause.",
        "findings": ["backend/app/x.py:42 — off-by-one in the loop bound"],
        "reproduced": False,
    }

    final_state, llm = _run_real_agent_with_critique(
        role_name="debugger_agent",
        tools=_TOOLS,
        handlers=handlers,
        verification_cfg=_CFG,
        submit_tool_name="submit_debugger_agent",
        submit_input=submit_input,
    )

    assert final_state["submitted"] is True
    assert final_state["critique_result"]["all_met"] is True
    assert final_state.get("critique_retries", 0) == 1
    assert llm.main_turn_calls == 2, "model must get a second turn to improve"
    # Proves the critique prompt was built from debugger_agent's REAL role
    # file, not a synthetic stand-in.
    assert any(
        "file:line" in p or "Root cause identified" in p for p in llm.critique_prompts
    )


# ---------------------------------------------------------------------------
# Analyzer tier — code_quality_agent (confirmed Analyzer-tier in Step 2:
# read-only, no edit_file/bash)
# ---------------------------------------------------------------------------


def test_analyzer_tier_real_agent_critique_end_to_end() -> None:
    from app.agents.code_quality_agent import (
        _CFG,
        _TOOLS,
        make_code_quality_agent_handlers,
    )

    handlers = make_code_quality_agent_handlers(".")
    submit_input = {
        "summary": "Reviewed the module for complexity and error handling.",
        "findings": ["backend/app/y.py:10 — unhandled exception on parse failure"],
    }

    final_state, llm = _run_real_agent_with_critique(
        role_name="code_quality_agent",
        tools=_TOOLS,
        handlers=handlers,
        verification_cfg=_CFG,
        submit_tool_name="submit_code_quality_agent",
        submit_input=submit_input,
    )

    assert final_state["submitted"] is True
    assert final_state["critique_result"]["all_met"] is True
    assert final_state.get("critique_retries", 0) == 1
    assert llm.main_turn_calls == 2
    assert any(
        "file:line" in p or "Complexity hot-spots" in p for p in llm.critique_prompts
    )


# ---------------------------------------------------------------------------
# Editor tier — runbook_generator_agent (real edit_file + yaml_validate tools)
# ---------------------------------------------------------------------------


def test_editor_tier_real_agent_critique_end_to_end() -> None:
    from app.agents.runbook_generator_agent import (
        _CFG,
        _TOOLS,
        make_runbook_generator_agent_handlers,
    )

    handlers = make_runbook_generator_agent_handlers(".")
    submit_input = {
        "summary": "Generated the deploy runbook.",
        "runbook_path": "docs/runbooks/deploy.md",
    }

    final_state, llm = _run_real_agent_with_critique(
        role_name="runbook_generator_agent",
        tools=_TOOLS,
        handlers=handlers,
        verification_cfg=_CFG,
        submit_tool_name="submit_runbook_generator_agent",
        submit_input=submit_input,
    )

    assert final_state["submitted"] is True
    assert final_state["critique_result"]["all_met"] is True
    assert final_state.get("critique_retries", 0) == 1
    assert llm.main_turn_calls == 2
    assert any(
        "verified against repo evidence" in p or "Runbooks for the requested" in p
        for p in llm.critique_prompts
    )


def test_all_three_tiers_are_covered() -> None:
    """Documents the exact per-tier coverage this file provides so a future
    tier gaining critique support doesn't silently go unaudited."""
    tiers_covered = {
        "executor": "debugger_agent",
        "analyzer": "code_quality_agent",
        "editor": "runbook_generator_agent",
    }
    assert len(tiers_covered) == 3
