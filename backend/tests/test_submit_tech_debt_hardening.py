"""submit_tech_debt tool #201 — tool_enhance.md productionization pass
(2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#192/#196-#200.
No injection surface. Not in CHAT_TOOLS (one-shot tech_debt_agent-only
tool, correct absence).

One real finding: `td_submit`'s local `tech_debt_result` dict was
updated on every call and exported as `handlers["_tech_debt_result"]`,
but NEVER read anywhere in the codebase — genuinely dead state. The
real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by tech_debt_agent.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    TECH_DEBT_AGENT_TOOLS,
    make_tech_debt_agent_handlers,
)
from app.tools.agents.submit_tech_debt import (
    SUBMIT_TECH_DEBT_TOOL,
    submit_tech_debt_handler,
)


def test_submit_tech_debt_tool_schema() -> None:
    assert SUBMIT_TECH_DEBT_TOOL["name"] == "submit_tech_debt"
    assert SUBMIT_TECH_DEBT_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_tech_debt_appears_exactly_once_in_tech_debt_agent_tools() -> None:
    names = [t["name"] for t in TECH_DEBT_AGENT_TOOLS]
    assert names.count("submit_tech_debt") == 1


def test_submit_tech_debt_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_tech_debt" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_tech_debt_result_key_exported(self) -> None:
        handlers = make_tech_debt_agent_handlers("/tmp")
        assert "_tech_debt_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_tech_debt_handler({"summary": "3 debt items found"})
        assert out == "Tech debt analysis submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_tech_debt_handler({})
        out_full = submit_tech_debt_handler(
            {
                "summary": "x",
                "debt_items": [{"file": "a.py", "line": 12, "severity": "medium"}],
                "priority_fixes": ["refactor a.py's god function"],
                "effort_estimate": "2 days",
            }
        )
        assert out_minimal == out_full == "Tech debt analysis submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_tech_debt_agent_handlers_wires_submit_tech_debt(self) -> None:
        handlers = make_tech_debt_agent_handlers("/tmp")
        assert "submit_tech_debt" in handlers
        out = handlers["submit_tech_debt"]({"summary": "Real submission"})
        assert out == "Tech debt analysis submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_tech_debt_agent_handlers("/tmp")
        out1 = handlers["submit_tech_debt"]({"summary": "first"})
        out2 = handlers["submit_tech_debt"]({"summary": "second"})
        assert out1 == out2 == "Tech debt analysis submitted"

    def test_other_tech_debt_agent_handlers_unaffected(self) -> None:
        handlers = make_tech_debt_agent_handlers("/tmp")
        for key in (
            "list_functions",
            "list_classes",
            "find_todos",
            "run_linter",
            "coverage_report",
            "submit_tech_debt",
        ):
            assert key in handlers
