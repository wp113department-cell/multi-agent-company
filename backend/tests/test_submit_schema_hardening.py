"""submit_schema tool #196 — tool_enhance.md productionization pass
(2026-09-16).

Same class and shape as sibling tools #180-#186/#188-#192. No
injection surface. Not in CHAT_TOOLS (one-shot schema_agent-only tool,
correct absence).

One real finding: `sa_submit`'s local `schema_result` dict was updated
on every call and exported as `handlers["_schema_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by schema_agent.py's own `raw = final_state["result"]` line,
which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    SCHEMA_AGENT_TOOLS,
    make_schema_agent_handlers,
)
from app.tools.agents.submit_schema import SUBMIT_SCHEMA_TOOL, submit_schema_handler


def test_submit_schema_tool_schema() -> None:
    assert SUBMIT_SCHEMA_TOOL["name"] == "submit_schema"
    assert SUBMIT_SCHEMA_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_schema_appears_exactly_once_in_schema_agent_tools() -> None:
    names = [t["name"] for t in SCHEMA_AGENT_TOOLS]
    assert names.count("submit_schema") == 1


def test_submit_schema_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_schema" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_schema_result_key_exported(self) -> None:
        handlers = make_schema_agent_handlers("/tmp")
        assert "_schema_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_schema_handler({"summary": "normalized users table"})
        assert out == "Schema design submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_schema_handler({})
        out_full = submit_schema_handler(
            {
                "summary": "x",
                "tables": [{"name": "users", "columns": ["id", "email"]}],
                "normalization_issues": ["denormalized address"],
                "files_written": ["schema.sql"],
            }
        )
        assert out_minimal == out_full == "Schema design submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_schema_agent_handlers_wires_submit_schema(self) -> None:
        handlers = make_schema_agent_handlers("/tmp")
        assert "submit_schema" in handlers
        out = handlers["submit_schema"]({"summary": "Real submission"})
        assert out == "Schema design submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_schema_agent_handlers("/tmp")
        out1 = handlers["submit_schema"]({"summary": "first"})
        out2 = handlers["submit_schema"]({"summary": "second"})
        assert out1 == out2 == "Schema design submitted"

    def test_other_schema_agent_handlers_unaffected(self) -> None:
        handlers = make_schema_agent_handlers("/tmp")
        for key in ("run_sql", "inspect_schema", "write_file", "submit_schema"):
            assert key in handlers
