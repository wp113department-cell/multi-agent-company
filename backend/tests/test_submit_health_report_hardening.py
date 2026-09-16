"""submit_health_report tool #187 — tool_enhance.md productionization
pass (2026-09-16).

IMPORTANT DIFFERENCE FROM SIBLING TOOLS #180-#186: this is NOT a dead
accumulator. `app/agents/devops.py::run_devops` reads
`handlers.get("_health_result", {})` directly to build its real
`HealthReport` return value — confirmed by reading the full function
body, including its explicit "Agent spoke but never called
submit_health_report" fallback when the dict is empty. No functional
bug found. Modularized purely for consistency with the already-
established `make_submit_docs_handler`/`docs_result` pattern (tool
#85) — the shared `bash` closure in the same factory function
(`make_devops_handlers`) is untouched, out of scope for this turn.

Not in CHAT_TOOLS — confirmed intentional (devops is a batch agent,
never exposed to interactive chat).
"""

from __future__ import annotations

from app.agents.tools import CHAT_TOOLS, DEVOPS_TOOLS, make_devops_handlers
from app.tools.agents.submit_health_report import (
    SUBMIT_HEALTH_REPORT_TOOL,
    make_submit_health_report_handler,
)


def test_submit_health_report_tool_schema() -> None:
    assert SUBMIT_HEALTH_REPORT_TOOL["name"] == "submit_health_report"
    assert SUBMIT_HEALTH_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "status",
        "checks",
        "summary",
    ]


def test_submit_health_report_appears_exactly_once_in_devops_tools() -> None:
    names = [t["name"] for t in DEVOPS_TOOLS]
    assert names.count("submit_health_report") == 1


def test_submit_health_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_health_report" not in names


# ---------------------------------------------------------------------------
# Real, live accumulator — genuinely read by run_devops(), not dead code
# ---------------------------------------------------------------------------


class TestRealResultSink:
    def test_make_submit_health_report_handler_stores_into_the_given_dict(self) -> None:
        health_result: dict = {}
        handler = make_submit_health_report_handler(health_result)
        result = handler(
            {
                "status": "healthy",
                "checks": [{"name": "db", "status": "ok", "detail": "connected"}],
                "summary": "all systems nominal",
            }
        )
        assert result == "Health report submitted"
        assert health_result["status"] == "healthy"
        assert health_result["summary"] == "all systems nominal"

    def test_make_submit_health_report_handler_uses_the_dict_it_was_given_not_a_copy(
        self,
    ) -> None:
        """run_devops() reads handlers["_health_result"] after the graph
        run finishes — the handler must mutate that exact object, not an
        internal copy, or the real result would never reach the caller."""
        health_result: dict = {}
        handler = make_submit_health_report_handler(health_result)
        handler({"status": "degraded", "checks": [], "summary": "disk low"})
        assert health_result["status"] == "degraded"

    def test_make_devops_handlers_exports_the_same_object_handler_writes_to(self) -> None:
        handlers = make_devops_handlers("/tmp")
        handlers["submit_health_report"](
            {"status": "unhealthy", "checks": [], "summary": "db down"}
        )
        assert handlers["_health_result"]["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_devops_handlers_wires_submit_health_report(self) -> None:
        handlers = make_devops_handlers("/tmp")
        assert "submit_health_report" in handlers
        assert "bash" in handlers

    def test_repeated_calls_accumulate_into_the_same_dict(self) -> None:
        """Matches update()-based semantics of the original implementation:
        a later call's fields overwrite earlier ones in the same dict,
        exactly as before this modularization."""
        handlers = make_devops_handlers("/tmp")
        handlers["submit_health_report"](
            {"status": "healthy", "checks": [], "summary": "first"}
        )
        handlers["submit_health_report"](
            {"status": "degraded", "checks": [], "summary": "second"}
        )
        assert handlers["_health_result"]["status"] == "degraded"
        assert handlers["_health_result"]["summary"] == "second"

    def test_independent_handler_instances_do_not_share_state(self) -> None:
        h1 = make_devops_handlers("/tmp")
        h2 = make_devops_handlers("/tmp")
        h1["submit_health_report"]({"status": "healthy", "checks": [], "summary": "h1"})
        assert "status" not in h2["_health_result"]
