"""submit_sql_report tool #199 — tool_enhance.md productionization
pass (2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#192/#196-#198.
No injection surface. Not in CHAT_TOOLS (one-shot sql_agent-only tool,
correct absence).

One real finding: `sq_submit`'s local `sql_result` dict was updated on
every call and exported as `handlers["_sql_result"]`, but NEVER read
anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by sql_agent.py's own `raw = final_state["result"]` line,
which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import CHAT_TOOLS, SQL_AGENT_TOOLS, make_sql_agent_handlers
from app.tools.agents.submit_sql_report import (
    SUBMIT_SQL_REPORT_TOOL,
    submit_sql_report_handler,
)


def test_submit_sql_report_tool_schema() -> None:
    assert SUBMIT_SQL_REPORT_TOOL["name"] == "submit_sql_report"
    assert SUBMIT_SQL_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "action",
        "result",
    ]


def test_submit_sql_report_appears_exactly_once_in_sql_agent_tools() -> None:
    names = [t["name"] for t in SQL_AGENT_TOOLS]
    assert names.count("submit_sql_report") == 1


def test_submit_sql_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_sql_report" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_sql_result_key_exported(self) -> None:
        handlers = make_sql_agent_handlers("/tmp")
        assert "_sql_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_sql_report_handler({"action": "query", "result": "1 row"})
        assert out == "SQL report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_sql_report_handler({})
        out_full = submit_sql_report_handler(
            {
                "action": "migration",
                "result": "created users table",
                "files_written": ["migrations/0001_init.sql"],
            }
        )
        assert out_minimal == out_full == "SQL report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_sql_agent_handlers_wires_submit_sql_report(self) -> None:
        handlers = make_sql_agent_handlers("/tmp")
        assert "submit_sql_report" in handlers
        out = handlers["submit_sql_report"](
            {"action": "query", "result": "Real submission"}
        )
        assert out == "SQL report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_sql_agent_handlers("/tmp")
        out1 = handlers["submit_sql_report"]({"action": "a", "result": "first"})
        out2 = handlers["submit_sql_report"]({"action": "b", "result": "second"})
        assert out1 == out2 == "SQL report submitted"

    def test_other_sql_agent_handlers_unaffected(self) -> None:
        handlers = make_sql_agent_handlers("/tmp")
        for key in (
            "run_sql",
            "inspect_schema",
            "find_sql",
            "explain_query",
            "edit_file",
            "write_file",
            "submit_sql_report",
        ):
            assert key in handlers
