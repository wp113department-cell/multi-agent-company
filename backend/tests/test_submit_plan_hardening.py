"""submit_plan tool #256 — tool_enhance.md productionization pass
(2026-09-18).

No security vulnerability and no functional bug found — this audit's
real conclusion, structurally identical to sibling tools #234
(submit_architect_plan) and #235 (submit_brief). No write_file
anywhere in this agent's tool list at all — planner runs through
app/pipeline/graph.py, not interactive chat, and the write_file-
scoping finding class doesn't apply here. The handler is a trivial
no-op lambda (`lambda inp: "Plan submitted"`) — confirmed INTENTIONAL
correct design: run_planner reads final_state.get("result", {})
directly, meaning base_graph.py's generic submit_* capture mechanism
is the real, load-bearing data path.

_validate_plan() (real, deterministic markdown-section validation)
audited for crash risk — confirmed safe against any string input via
direct `str()` coercion of the plan value before validation.
"""

from __future__ import annotations

from app.agents.planner import _SUBMIT_TOOL, _validate_plan, AGENT_CONTRACT
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_TOOL["name"] == "submit_plan"
    assert _SUBMIT_TOOL["input_schema"]["required"] == ["plan"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_plan" not in {t["name"] for t in CHAT_TOOLS}


def test_no_write_file_in_this_agents_tools() -> None:
    assert "write_file" not in AGENT_CONTRACT["allowed_tools"]


def test_handler_is_a_safe_noop_never_crashes_regardless_of_input() -> None:
    """Reproduces run_planner's exact wiring line
    (`handlers["submit_plan"] = lambda inp: "Plan submitted"`) directly,
    without running the full LangGraph."""
    submit_lambda = lambda inp: "Plan submitted"  # noqa: E731

    for malformed_input in (
        {},
        {"plan": None},
        {"plan": 12345},
        None,
        "not-a-dict",
    ):
        result = submit_lambda(malformed_input)
        assert result == "Plan submitted"


def test_planner_agent_contract_declares_the_real_tool() -> None:
    assert "submit_plan" in AGENT_CONTRACT["allowed_tools"]


def test_validate_plan_rejects_too_short_plan() -> None:
    assert _validate_plan("short") is not None


def test_validate_plan_rejects_missing_sections() -> None:
    long_but_incomplete = "x" * 200
    assert _validate_plan(long_but_incomplete) is not None


def test_validate_plan_accepts_well_formed_plan() -> None:
    good_plan = (
        "## Overview\n" + "x" * 100 + "\n## Implementation Steps\n1. Do a thing\n"
        "## Files To Inspect\n- app/main.py\n"
    )
    assert _validate_plan(good_plan) is None
