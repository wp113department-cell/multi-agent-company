"""submit_ba_result tool #182 — tool_enhance.md productionization
pass (2026-09-15).

Same class and shape as sibling tools #180/#181. No injection
surface. Not in CHAT_TOOLS (one-shot business_analyst-only tool,
correct absence).

One real finding: `ba_submit`'s local `ba_result` dict was updated on
every call and exported as `handlers["_ba_result"]`, but NEVER read
anywhere in the codebase — genuinely dead state. The real result-
capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by business_analyst.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    BUSINESS_ANALYST_TOOLS,
    CHAT_TOOLS,
    make_business_analyst_handlers,
)
from app.tools.agents.submit_ba_result import (
    SUBMIT_BA_RESULT_TOOL,
    submit_ba_result_handler,
)


def test_submit_ba_result_tool_schema() -> None:
    assert SUBMIT_BA_RESULT_TOOL["name"] == "submit_ba_result"
    assert SUBMIT_BA_RESULT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "user_stories",
        "summary",
    ]


def test_submit_ba_result_appears_exactly_once_in_business_analyst_tools() -> None:
    names = [t["name"] for t in BUSINESS_ANALYST_TOOLS]
    assert names.count("submit_ba_result") == 1


def test_submit_ba_result_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_ba_result" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_ba_result_key_exported(self) -> None:
        handlers = make_business_analyst_handlers("/tmp")
        assert "_ba_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_ba_result_handler(
            {"user_stories": ["As a user, I want..."], "summary": "done"}
        )
        assert out == "Business analysis submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_ba_result_handler({})
        out_full = submit_ba_result_handler(
            {
                "user_stories": ["story 1", "story 2"],
                "acceptance_criteria": ["ac1"],
                "edge_cases": ["ec1"],
                "summary": "x",
            }
        )
        assert out_minimal == out_full == "Business analysis submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_business_analyst_handlers_wires_submit_ba_result(self) -> None:
        handlers = make_business_analyst_handlers("/tmp")
        assert "submit_ba_result" in handlers
        out = handlers["submit_ba_result"](
            {"user_stories": ["Real story"], "summary": "Real submission"}
        )
        assert out == "Business analysis submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_business_analyst_handlers("/tmp")
        out1 = handlers["submit_ba_result"]({"user_stories": ["first"], "summary": "a"})
        out2 = handlers["submit_ba_result"]({"user_stories": ["second"], "summary": "b"})
        assert out1 == out2 == "Business analysis submitted"
