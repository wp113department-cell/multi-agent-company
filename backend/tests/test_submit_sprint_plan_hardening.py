"""submit_sprint_plan tool #198 — tool_enhance.md productionization
pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#192/#196/#197.
No injection surface. Not in CHAT_TOOLS (one-shot sprint_planner-only
tool, correct absence).

One real finding: `sp_submit`'s local `sprint_result` dict was updated
on every call and exported as `handlers["_sprint_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by sprint_planner.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    SPRINT_PLANNER_TOOLS,
    make_sprint_planner_handlers,
)
from app.tools.agents.submit_sprint_plan import (
    SUBMIT_SPRINT_PLAN_TOOL,
    submit_sprint_plan_handler,
)


def test_submit_sprint_plan_tool_schema() -> None:
    assert SUBMIT_SPRINT_PLAN_TOOL["name"] == "submit_sprint_plan"
    assert SUBMIT_SPRINT_PLAN_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "goal",
        "stories",
    ]


def test_submit_sprint_plan_appears_exactly_once_in_sprint_planner_tools() -> None:
    names = [t["name"] for t in SPRINT_PLANNER_TOOLS]
    assert names.count("submit_sprint_plan") == 1


def test_submit_sprint_plan_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_sprint_plan" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_sprint_result_key_exported(self) -> None:
        handlers = make_sprint_planner_handlers("/tmp")
        assert "_sprint_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_sprint_plan_handler({"goal": "ship auth", "stories": []})
        assert out == "Sprint plan submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_sprint_plan_handler({})
        out_full = submit_sprint_plan_handler(
            {
                "goal": "x",
                "stories": [{"title": "login", "estimate": 3}],
                "total_points": 3,
                "risks": ["oauth provider downtime"],
            }
        )
        assert out_minimal == out_full == "Sprint plan submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_sprint_planner_handlers_wires_submit_sprint_plan(self) -> None:
        handlers = make_sprint_planner_handlers("/tmp")
        assert "submit_sprint_plan" in handlers
        out = handlers["submit_sprint_plan"](
            {"goal": "Real submission", "stories": []}
        )
        assert out == "Sprint plan submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_sprint_planner_handlers("/tmp")
        out1 = handlers["submit_sprint_plan"]({"goal": "first", "stories": []})
        out2 = handlers["submit_sprint_plan"]({"goal": "second", "stories": []})
        assert out1 == out2 == "Sprint plan submitted"

    def test_other_sprint_planner_handlers_unaffected(self) -> None:
        handlers = make_sprint_planner_handlers("/tmp")
        for key in ("estimate_complexity", "submit_sprint_plan"):
            assert key in handlers
