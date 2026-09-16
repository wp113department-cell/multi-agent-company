"""submit_refactor_report tool #192 — tool_enhance.md
productionization pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#191. No
injection surface. Not in CHAT_TOOLS (one-shot refactor_agent-only
tool, correct absence). This is the exact sibling tool
`submit_cicd_report`'s own docstring (tool #183) explicitly named as
sharing its dead-accumulator pattern but deliberately deferred to its
own turn — this turn closes that deferred item.

One real finding: `rf_submit`'s local `refactor_result` dict was
updated on every call and exported as `handlers["_refactor_result"]`,
but NEVER read anywhere in the codebase — genuinely dead state. The
real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by refactor_agent.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    REFACTOR_AGENT_TOOLS,
    make_refactor_agent_handlers,
)
from app.tools.agents.submit_refactor_report import (
    SUBMIT_REFACTOR_REPORT_TOOL,
    submit_refactor_report_handler,
)


def test_submit_refactor_report_tool_schema() -> None:
    assert SUBMIT_REFACTOR_REPORT_TOOL["name"] == "submit_refactor_report"
    assert SUBMIT_REFACTOR_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "summary",
        "files_changed",
    ]


def test_submit_refactor_report_appears_exactly_once_in_refactor_agent_tools() -> (
    None
):
    names = [t["name"] for t in REFACTOR_AGENT_TOOLS]
    assert names.count("submit_refactor_report") == 1


def test_submit_refactor_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_refactor_report" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_refactor_result_key_exported(self) -> None:
        handlers = make_refactor_agent_handlers("/tmp")
        assert "_refactor_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_refactor_report_handler(
            {"summary": "extracted helper", "files_changed": ["a.py"]}
        )
        assert out == "Refactor report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_refactor_report_handler({})
        out_full = submit_refactor_report_handler(
            {
                "summary": "x",
                "files_changed": ["a.py", "b.py"],
                "breaking_changes": True,
            }
        )
        assert out_minimal == out_full == "Refactor report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_refactor_agent_handlers_wires_submit_refactor_report(self) -> None:
        handlers = make_refactor_agent_handlers("/tmp")
        assert "submit_refactor_report" in handlers
        out = handlers["submit_refactor_report"](
            {"summary": "Real submission", "files_changed": []}
        )
        assert out == "Refactor report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_refactor_agent_handlers("/tmp")
        out1 = handlers["submit_refactor_report"](
            {"summary": "first", "files_changed": []}
        )
        out2 = handlers["submit_refactor_report"](
            {"summary": "second", "files_changed": []}
        )
        assert out1 == out2 == "Refactor report submitted"

    def test_other_refactor_agent_handlers_unaffected(self) -> None:
        handlers = make_refactor_agent_handlers("/tmp")
        for key in (
            "list_functions",
            "list_classes",
            "find_function_body",
            "parse_ast",
            "call_graph",
            "import_graph",
            "rename_symbol",
            "replace_function",
            "edit_file",
            "write_file",
            "git_diff",
            "bash",
            "submit_refactor_report",
        ):
            assert key in handlers
