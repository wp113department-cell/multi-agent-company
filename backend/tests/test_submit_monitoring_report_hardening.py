"""submit_monitoring_report tool #189 — tool_enhance.md
productionization pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188. No injection
surface. Not in CHAT_TOOLS (one-shot monitoring_agent-only tool,
correct absence). Also correctly excluded from monitoring_agent.py's
own SCAN_TOOLS (autonomous scan-loop variant swaps it for
submit_enhancement_request by pre-existing, documented design) —
untouched here.

One real finding: `mon_submit`'s local `monitoring_result` dict was
updated on every call and exported as `handlers["_monitoring_result"]`,
but NEVER read anywhere in the codebase — genuinely dead state. The
real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by run_monitoring_agent()'s own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.monitoring_agent import SCAN_TOOLS
from app.agents.tools import (
    CHAT_TOOLS,
    MONITORING_AGENT_TOOLS,
    make_monitoring_agent_handlers,
)
from app.tools.agents.submit_monitoring_report import (
    SUBMIT_MONITORING_REPORT_TOOL,
    submit_monitoring_report_handler,
)


def test_submit_monitoring_report_tool_schema() -> None:
    assert SUBMIT_MONITORING_REPORT_TOOL["name"] == "submit_monitoring_report"
    assert SUBMIT_MONITORING_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "status",
        "metrics",
    ]


def test_submit_monitoring_report_appears_exactly_once_in_monitoring_agent_tools() -> (
    None
):
    names = [t["name"] for t in MONITORING_AGENT_TOOLS]
    assert names.count("submit_monitoring_report") == 1


def test_submit_monitoring_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_monitoring_report" not in names


def test_submit_monitoring_report_correctly_excluded_from_scan_tools() -> None:
    """Pre-existing, documented design: the autonomous scan loop swaps
    this one-shot terminal tool for submit_enhancement_request. Not a
    bug — re-confirmed here, not re-fixed."""
    names = [t["name"] for t in SCAN_TOOLS]
    assert "submit_monitoring_report" not in names
    assert "submit_enhancement_request" in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_monitoring_result_key_exported(self) -> None:
        handlers = make_monitoring_agent_handlers("/tmp")
        assert "_monitoring_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_monitoring_report_handler(
            {"status": "healthy", "metrics": {"cpu": "5%"}}
        )
        assert out == "Monitoring report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_monitoring_report_handler({})
        out_full = submit_monitoring_report_handler(
            {
                "status": "critical",
                "metrics": {"cpu": "99%", "mem": "95%"},
                "issues": ["disk almost full"],
                "recommendations": ["scale up"],
            }
        )
        assert out_minimal == out_full == "Monitoring report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_monitoring_agent_handlers_wires_submit_monitoring_report(
        self,
    ) -> None:
        handlers = make_monitoring_agent_handlers("/tmp")
        assert "submit_monitoring_report" in handlers
        out = handlers["submit_monitoring_report"]({"status": "healthy", "metrics": {}})
        assert out == "Monitoring report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_monitoring_agent_handlers("/tmp")
        out1 = handlers["submit_monitoring_report"](
            {"status": "healthy", "metrics": {}}
        )
        out2 = handlers["submit_monitoring_report"](
            {"status": "warning", "metrics": {}}
        )
        assert out1 == out2 == "Monitoring report submitted"

    def test_other_monitoring_agent_handlers_unaffected(self) -> None:
        handlers = make_monitoring_agent_handlers("/tmp")
        for key in (
            "cpu_usage",
            "memory_usage",
            "disk_usage",
            "health_check",
            "task_progress",
            "read_logs",
            "submit_monitoring_report",
        ):
            assert key in handlers
