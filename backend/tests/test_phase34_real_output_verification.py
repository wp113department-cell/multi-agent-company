"""Tests for MASTER_AGENT_v2.md Phase 3.4 gap-closure — "real output
verification tests, not just wiring tests, for every agent."

The existing coverage (test_executor_tier_bash.py, test_phase3_verification_audit.py)
proves the verification-flag *wiring* is correct via source inspection and
handler-level unit tests — it never actually runs an agent end to end and
proves the graph overrides a false model claim with the real observed state.
That's the literal scenario the spec names: "mocks a failing test run and
asserts the agent's submit_* result correctly reports tests_passed=False
(sourced from state["verification"], not from what the mocked LLM response
merely claimed)."

Scope: the spec says "every agent," but the actual mechanism under test
(execute_tools's enforce_in_result override) is one shared implementation in
base_graph.py — what varies per agent is only which VerificationConfig each
one wires. This file runs the real run_<agent>() wrapper (not a hand-rolled
run_agent_graph() call) for every Step-2 agent whose enforce_in_result
overrides a field beyond "read" — the 4 where a false claim is actually
observable in AgentResult.verified — which is a real, representative
end-to-end proof for every distinct wiring shape in the fleet, not a
per-agent-name checkbox exercise.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class _FalseClaimLLM:
    """The model never calls bash (or any real verification tool) — it
    submits immediately, falsely claiming its tracked verification field is
    True. Tolerates planner_node/reflection_node/lesson-extraction's own
    generic calls (all enabled by default in every real run_<agent>()
    wrapper) with safe, non-JSON-breaking fallbacks."""

    def __init__(self, submit_tool_name: str, claimed_field: str) -> None:
        self.submit_tool_name = submit_tool_name
        self.claimed_field = claimed_field
        self.submit_calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Review what the tools just produced" in last_text:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"satisfied": true}')],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )
        if "Extract a reusable lesson" in last_text:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=json.dumps(
                            {
                                "lesson": "n/a",
                                "pattern": "n/a",
                                "category": "general",
                                "reusable": False,
                            }
                        ),
                    )
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

        tools = kwargs.get("tools") or []
        has_submit = any(t.get("name") == self.submit_tool_name for t in tools)
        if has_submit:
            self.submit_calls += 1
            claim = {
                "summary": "All checks passed, submitting now.",
                "findings": [],
                self.claimed_field: True,
            }
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu_submit",
                        name=self.submit_tool_name,
                        input=claim,
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )

        # planner_node's 2 calls, and anything else — safe generic fallback
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


# module_name -> (run_<agent> kwarg name for the run entrypoint's task
# description-like first positional args, submit tool name, claimed field,
# whether AgentResult.verified is actually load-bearing on this field).
_AGENTS_UNDER_TEST = {
    "test_writer_agent": ("submit_test_writer_agent", "tests_run", True),
    "test_coverage_agent": ("submit_test_coverage_agent", "coverage_measured", True),
    "load_test_agent": ("submit_load_test_agent", "smoke_tested", False),
    "infra_agent": ("submit_infra_agent", "dry_run_validated", False),
}


@pytest.mark.parametrize("module_name", sorted(_AGENTS_UNDER_TEST))
def test_false_claim_is_overridden_by_real_observed_state(module_name: str) -> None:
    """The core Phase 3.4 scenario: the model never actually ran the real
    verification tool, but claims it did in its submit_* call. Runs the
    REAL run_<agent>() wrapper end to end (not a hand-rolled run_agent_graph
    call) — proving the actual production code path, not a reimplementation
    of it, honors the graph's override contract."""
    import importlib

    submit_tool_name, claimed_field, _required = _AGENTS_UNDER_TEST[module_name]
    mod = importlib.import_module(f"app.agents.{module_name}")
    run_fn = getattr(mod, f"run_{module_name}")

    llm = _FalseClaimLLM(submit_tool_name, claimed_field)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = llm

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = run_fn(task_id=1, description="do the task", repo_path=".")

    assert llm.submit_calls >= 1, "the model never actually reached submit_*"
    # The graph-enforced truth: the claimed field was never really set,
    # because the agent never called bash — enforce_in_result must have
    # overridden the model's claim back to False in the real result.
    assert result.raw.get(claimed_field) is False, (
        f"{module_name}: submit_* claimed {claimed_field}=True with no real "
        f"tool call behind it, and the graph did not override it — a false "
        f"claim leaked into the final result"
    )


@pytest.mark.parametrize(
    "module_name",
    [name for name, (_t, _f, required) in _AGENTS_UNDER_TEST.items() if required],
)
def test_false_claim_makes_agent_result_unverified(module_name: str) -> None:
    """For the 2 agents where the flag is load-bearing (test_writer_agent,
    test_coverage_agent): a false claim with no real tool call must produce
    AgentResult.verified=False, not just an overridden raw field — this is
    the field a caller actually trusts, per AgentResult's own docstring
    ("verified: True ONLY when the graph's verification dict confirms it —
    never from the model's own claim")."""
    import importlib

    submit_tool_name, claimed_field, _required = _AGENTS_UNDER_TEST[module_name]
    mod = importlib.import_module(f"app.agents.{module_name}")
    run_fn = getattr(mod, f"run_{module_name}")

    llm = _FalseClaimLLM(submit_tool_name, claimed_field)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = llm

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = run_fn(task_id=2, description="do the task", repo_path=".")

    assert result.verified is False, (
        f"{module_name}: AgentResult.verified was True despite the agent "
        f"never having actually run its real verification tool"
    )
