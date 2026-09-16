"""submit_style_review tool #200 — tool_enhance.md productionization
pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#192/#196-#199.
No injection surface. Not in CHAT_TOOLS (one-shot style_reviewer-only
tool, correct absence).

One real finding: `sr_submit`'s local `style_result` dict was updated
on every call and exported as `handlers["_style_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by style_reviewer.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    STYLE_REVIEWER_TOOLS,
    make_style_reviewer_handlers,
)
from app.tools.agents.submit_style_review import (
    SUBMIT_STYLE_REVIEW_TOOL,
    submit_style_review_handler,
)


def test_submit_style_review_tool_schema() -> None:
    assert SUBMIT_STYLE_REVIEW_TOOL["name"] == "submit_style_review"
    assert SUBMIT_STYLE_REVIEW_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_style_review_appears_exactly_once_in_style_reviewer_tools() -> None:
    names = [t["name"] for t in STYLE_REVIEWER_TOOLS]
    assert names.count("submit_style_review") == 1


def test_submit_style_review_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_style_review" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_style_result_key_exported(self) -> None:
        handlers = make_style_reviewer_handlers("/tmp")
        assert "_style_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_style_review_handler({"summary": "3 lint violations"})
        assert out == "Style review submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_style_review_handler({})
        out_full = submit_style_review_handler(
            {
                "summary": "x",
                "violations": [{"file": "a.py", "line": 5, "rule": "E501"}],
                "auto_fixable": True,
            }
        )
        assert out_minimal == out_full == "Style review submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_style_reviewer_handlers_wires_submit_style_review(self) -> None:
        handlers = make_style_reviewer_handlers("/tmp")
        assert "submit_style_review" in handlers
        out = handlers["submit_style_review"]({"summary": "Real submission"})
        assert out == "Style review submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_style_reviewer_handlers("/tmp")
        out1 = handlers["submit_style_review"]({"summary": "first"})
        out2 = handlers["submit_style_review"]({"summary": "second"})
        assert out1 == out2 == "Style review submitted"

    def test_other_style_reviewer_handlers_unaffected(self) -> None:
        handlers = make_style_reviewer_handlers("/tmp")
        for key in (
            "run_linter",
            "list_functions",
            "list_classes",
            "find_todos",
            "submit_style_review",
        ):
            assert key in handlers
