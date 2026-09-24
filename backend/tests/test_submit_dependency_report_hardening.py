"""submit_dependency_report tool #185 — tool_enhance.md productionization
pass (2026-09-16).

Same class and shape as sibling tools #180/#181/#182/#183/#184. No
injection surface. Not in CHAT_TOOLS (one-shot dependency_agent-only
tool, correct absence). The schema's `manifest_read` field is
verification-gated (never trusted from the model's own claim) — that
protection was already correct and is re-confirmed here, not part of
this turn's finding.

One real finding: `dep_submit`'s local `dep_result` dict was updated
on every call and exported as `handlers["_dependency_result"]`, but
the only real reader anywhere in the codebase was a test asserting
directly on that dead key (tests/test_day2_agents.py) — never real
production code. The real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by run_dependency_agent()'s own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    DEPENDENCY_AGENT_TOOLS,
    make_dependency_agent_handlers,
)
from app.tools.agents.submit_dependency_report import (
    SUBMIT_DEPENDENCY_REPORT_TOOL,
    submit_dependency_report_handler,
)


def test_submit_dependency_report_tool_schema() -> None:
    assert SUBMIT_DEPENDENCY_REPORT_TOOL["name"] == "submit_dependency_report"
    assert SUBMIT_DEPENDENCY_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "dependencies",
        "summary",
        "manifest_read",
    ]


def test_submit_dependency_report_appears_exactly_once_in_dependency_agent_tools() -> (
    None
):
    names = [t["name"] for t in DEPENDENCY_AGENT_TOOLS]
    assert names.count("submit_dependency_report") == 1


def test_submit_dependency_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_dependency_report" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_dependency_result_key_exported(self) -> None:
        handlers = make_dependency_agent_handlers("/tmp")
        assert "_dependency_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_dependency_report_handler(
            {"dependencies": [], "summary": "none", "manifest_read": True}
        )
        assert out == "Dependency report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_dependency_report_handler({})
        out_full = submit_dependency_report_handler(
            {
                "dependencies": [
                    {
                        "name": "fastapi",
                        "current_version": "0.111.0",
                        "latest_version": "0.112.0",
                        "upgrade_recommended": True,
                    }
                ],
                "summary": "1 dependency checked",
                "files_changed": ["requirements.txt"],
                "manifest_read": True,
            }
        )
        assert out_minimal == out_full == "Dependency report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_dependency_agent_handlers_wires_submit_dependency_report(
        self,
    ) -> None:
        handlers = make_dependency_agent_handlers("/tmp")
        assert "submit_dependency_report" in handlers
        out = handlers["submit_dependency_report"](
            {"dependencies": [], "summary": "Real submission", "manifest_read": True}
        )
        assert out == "Dependency report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_dependency_agent_handlers("/tmp")
        out1 = handlers["submit_dependency_report"](
            {"dependencies": [], "summary": "first", "manifest_read": True}
        )
        out2 = handlers["submit_dependency_report"](
            {"dependencies": [], "summary": "second", "manifest_read": True}
        )
        assert out1 == out2 == "Dependency report submitted"

    def test_other_dependency_agent_handlers_unaffected(self) -> None:
        handlers = make_dependency_agent_handlers("/tmp")
        for key in (
            "bash",
            "edit_file",
            "check_last_release",
            "submit_dependency_report",
        ):
            assert key in handlers
