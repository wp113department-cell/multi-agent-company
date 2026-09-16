"""submit_perf_review tool #190 — tool_enhance.md productionization
pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188/#189. No
injection surface. Not in CHAT_TOOLS (one-shot
performance_reviewer-only tool, correct absence).

One real finding: `pr_submit`'s local `perf_result` dict was updated
on every call and exported as `handlers["_perf_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by performance_reviewer.py's own
`raw = final_state["result"]` line, which is what real production
code actually consumes. Fixed by removing the dead accumulator; the
handler now just returns the same confirmation string as before, with
zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    PERFORMANCE_REVIEWER_TOOLS,
    make_performance_reviewer_handlers,
)
from app.tools.agents.submit_perf_review import (
    SUBMIT_PERF_REVIEW_TOOL,
    submit_perf_review_handler,
)


def test_submit_perf_review_tool_schema() -> None:
    assert SUBMIT_PERF_REVIEW_TOOL["name"] == "submit_perf_review"
    assert SUBMIT_PERF_REVIEW_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_perf_review_appears_exactly_once_in_performance_reviewer_tools() -> (
    None
):
    names = [t["name"] for t in PERFORMANCE_REVIEWER_TOOLS]
    assert names.count("submit_perf_review") == 1


def test_submit_perf_review_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_perf_review" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_perf_result_key_exported(self) -> None:
        handlers = make_performance_reviewer_handlers("/tmp")
        assert "_perf_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_perf_review_handler({"summary": "N+1 query in list endpoint"})
        assert out == "Performance review submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_perf_review_handler({})
        out_full = submit_perf_review_handler(
            {
                "summary": "x",
                "findings": [{"file": "a.py", "issue": "N+1 query"}],
                "severity": "high",
                "recommendations": ["add eager loading"],
            }
        )
        assert out_minimal == out_full == "Performance review submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_performance_reviewer_handlers_wires_submit_perf_review(self) -> None:
        handlers = make_performance_reviewer_handlers("/tmp")
        assert "submit_perf_review" in handlers
        out = handlers["submit_perf_review"]({"summary": "Real submission"})
        assert out == "Performance review submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_performance_reviewer_handlers("/tmp")
        out1 = handlers["submit_perf_review"]({"summary": "first"})
        out2 = handlers["submit_perf_review"]({"summary": "second"})
        assert out1 == out2 == "Performance review submitted"

    def test_other_performance_reviewer_handlers_unaffected(self) -> None:
        handlers = make_performance_reviewer_handlers("/tmp")
        for key in (
            "find_sql",
            "run_sql",
            "explain_query",
            "list_functions",
            "submit_perf_review",
        ):
            assert key in handlers
