"""submit_security_report tool #197 — tool_enhance.md
productionization pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#192/#196. No
injection surface. Not in CHAT_TOOLS (one-shot security_reviewer-only
tool, correct absence). Also correctly excluded from
quality_auditor.py's own scan-scoped tool list (pre-existing,
documented design, mirroring monitoring_agent.py's scan-mode pattern)
— untouched.

Note: an unrelated agent, security_architect.py, coincidentally
exports its own local dict under the identically-named key
`handlers["_security_result"]` for its own different tool
(`submit_threat_model`) — a separate closure in a separate factory
function, not a real reader of this tool's dict. Several tests matched
by a naive grep (`test_day4_agents.py`, `test_gap_agents.py`,
`test_day4_agent_contracts.py`) actually test security_architect.py,
not this tool — verified by reading each, none required a change.

One real finding: `sec_submit`'s local `security_result` dict was
updated on every call and exported as `handlers["_security_result"]`,
but NEVER read anywhere in the codebase — genuinely dead state. The
real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by security_reviewer.py's own `raw = final_state["result"]`
lines (used on both its normal-completion and retry-giveup paths),
which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.quality_auditor import SCAN_TOOLS as QA_SCAN_TOOLS
from app.agents.tools import (
    CHAT_TOOLS,
    SECURITY_REVIEWER_TOOLS,
    make_security_reviewer_handlers,
)
from app.tools.agents.submit_security_report import (
    SUBMIT_SECURITY_REPORT_TOOL,
    submit_security_report_handler,
)


def test_submit_security_report_tool_schema() -> None:
    assert SUBMIT_SECURITY_REPORT_TOOL["name"] == "submit_security_report"
    assert SUBMIT_SECURITY_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "severity",
        "findings",
        "recommendations",
    ]


def test_submit_security_report_appears_exactly_once_in_security_reviewer_tools() -> (
    None
):
    names = [t["name"] for t in SECURITY_REVIEWER_TOOLS]
    assert names.count("submit_security_report") == 1


def test_submit_security_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_security_report" not in names


def test_submit_security_report_correctly_excluded_from_quality_auditor_scan_tools() -> (
    None
):
    """Pre-existing, documented design: quality_auditor.py's scan-scoped
    tool list swaps this one-shot terminal tool for something else. Not
    a bug — re-confirmed here, not re-fixed."""
    names = [t["name"] for t in QA_SCAN_TOOLS]
    assert "submit_security_report" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_security_result_key_exported(self) -> None:
        handlers = make_security_reviewer_handlers("/tmp")
        assert "_security_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_security_report_handler(
            {"severity": "low", "findings": [], "recommendations": []}
        )
        assert out == "Security report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_security_report_handler({})
        out_full = submit_security_report_handler(
            {
                "severity": "critical",
                "findings": ["SQL injection in login"],
                "recommendations": ["use parameterized queries"],
            }
        )
        assert out_minimal == out_full == "Security report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_security_reviewer_handlers_wires_submit_security_report(
        self,
    ) -> None:
        handlers = make_security_reviewer_handlers("/tmp")
        assert "submit_security_report" in handlers
        out = handlers["submit_security_report"](
            {"severity": "low", "findings": [], "recommendations": []}
        )
        assert out == "Security report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_security_reviewer_handlers("/tmp")
        out1 = handlers["submit_security_report"](
            {"severity": "low", "findings": [], "recommendations": []}
        )
        out2 = handlers["submit_security_report"](
            {"severity": "high", "findings": [], "recommendations": []}
        )
        assert out1 == out2 == "Security report submitted"

    def test_other_security_reviewer_handlers_unaffected(self) -> None:
        handlers = make_security_reviewer_handlers("/tmp")
        for key in (
            "secrets_scan",
            "find_sql",
            "find_config",
            "find_api",
            "find_route",
            "submit_security_report",
        ):
            assert key in handlers
