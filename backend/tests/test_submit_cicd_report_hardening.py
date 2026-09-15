"""submit_cicd_report tool #183 — tool_enhance.md productionization
pass (2026-09-15).

Same class and shape as sibling tools #180/#181/#182. No injection
surface. Not in CHAT_TOOLS (one-shot cicd_agent-only tool, correct
absence).

One real finding: `ci_submit`'s local `cicd_result` dict was updated
on every call and exported as `handlers["_cicd_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by cicd_agent.py's own `raw = final_state["result"]` line,
which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    CICD_AGENT_TOOLS,
    make_cicd_agent_handlers,
)
from app.tools.agents.submit_cicd_report import (
    SUBMIT_CICD_REPORT_TOOL,
    submit_cicd_report_handler,
)


def test_submit_cicd_report_tool_schema() -> None:
    assert SUBMIT_CICD_REPORT_TOOL["name"] == "submit_cicd_report"
    assert SUBMIT_CICD_REPORT_TOOL["input_schema"]["required"] == ["analysis"]  # type: ignore[index]


def test_submit_cicd_report_appears_exactly_once_in_cicd_agent_tools() -> None:
    names = [t["name"] for t in CICD_AGENT_TOOLS]
    assert names.count("submit_cicd_report") == 1


def test_submit_cicd_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_cicd_report" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_cicd_result_key_exported(self) -> None:
        handlers = make_cicd_agent_handlers("/tmp")
        assert "_cicd_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_cicd_report_handler({"analysis": "build failed"})
        assert out == "CI/CD report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_cicd_report_handler({})
        out_full = submit_cicd_report_handler(
            {
                "analysis": "x",
                "files_written": ["ci.yml"],
                "recommendations": ["r1"],
            }
        )
        assert out_minimal == out_full == "CI/CD report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_cicd_agent_handlers_wires_submit_cicd_report(self) -> None:
        handlers = make_cicd_agent_handlers("/tmp")
        assert "submit_cicd_report" in handlers
        out = handlers["submit_cicd_report"]({"analysis": "Real submission"})
        assert out == "CI/CD report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_cicd_agent_handlers("/tmp")
        out1 = handlers["submit_cicd_report"]({"analysis": "first"})
        out2 = handlers["submit_cicd_report"]({"analysis": "second"})
        assert out1 == out2 == "CI/CD report submitted"
