"""run_sql tool #15 — tool_enhance.md productionization pass (2026-08-17).

Real, empirically-verified finding (the most severe of this initiative
since the high-risk tier — a proven, live SQL injection, not a
theoretical one): both real implementations that accept `params`
(chat_agent.py's dispatch and make_chat_handlers's own) did naive string
substitution — `query.replace(f"${i}", f"'{param}'")` — with zero
escaping. Proved directly against the real project database (read-only,
no data modified) that a param value of
`"x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; --"` broke out of
its intended string literal and executed as a real, separate stacked SQL
statement.

Per the user's explicit scope decision, fixed via real parameter binding
(psycopg2) instead of hand-rolled escaping — `$N` placeholders are
converted to psycopg2's native `%s` style and values are bound
out-of-band over the wire protocol, never string-interpolated into SQL
text.

These tests require a real, reachable PostgreSQL database (DATABASE_URL)
— skipped otherwise, matching this codebase's existing convention for
DB-dependent tests.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database.sql import (
    RUN_SQL_TOOL,
    _convert_placeholders,
    run_sql_handler,
)

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)


def _db_url() -> str:
    return get_settings().database_url


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_run_sql_hardening", repo_path=repo)
    return ChatAgent(session)


def test_run_sql_tool_schema_has_required_fields() -> None:
    assert RUN_SQL_TOOL["name"] == "run_sql"
    assert RUN_SQL_TOOL["input_schema"]["required"] == ["query"]


# ---------------------------------------------------------------------------
# Placeholder-conversion unit tests (pure, no DB needed)
# ---------------------------------------------------------------------------


def test_convert_placeholders_simple_positional() -> None:
    converted, bound, error = _convert_placeholders("SELECT $1", ["a"])
    assert error is None
    assert converted == "SELECT %s"
    assert bound == ("a",)


def test_convert_placeholders_reorders_to_occurrence_order() -> None:
    converted, bound, error = _convert_placeholders(
        "WHERE b = $2 AND a = $1", ["A", "B"]
    )
    assert error is None
    assert converted == "WHERE b = %s AND a = %s"
    assert bound == ("B", "A")


def test_convert_placeholders_repeated_reference() -> None:
    converted, bound, error = _convert_placeholders("$1 = $1", ["x"])
    assert error is None
    assert converted == "%s = %s"
    assert bound == ("x", "x")


def test_convert_placeholders_out_of_range_is_an_error() -> None:
    converted, bound, error = _convert_placeholders("SELECT $1", [])
    assert error is not None
    assert "$1" in error


# ---------------------------------------------------------------------------
# The real, proven exploit — verified closed against a real database
# ---------------------------------------------------------------------------


def test_handler_treats_malicious_param_as_opaque_data_not_sql() -> None:
    """The exact proven exploit: a param value shaped like a SQL-injection
    stacked-statement payload must come back as a single literal row
    value, not execute as a second statement."""
    payload = "x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; --"
    result = run_sql_handler(_db_url(), {"query": "SELECT $1 AS col", "params": [payload]})
    # The full payload — including the semicolons and SELECT keyword —
    # must appear intact as ONE literal value, proving it was bound as
    # data, not parsed as SQL syntax.
    assert payload in result
    assert "(1 row(s))" in result


def test_handler_treats_single_quote_param_as_opaque_data() -> None:
    result = run_sql_handler(
        _db_url(), {"query": "SELECT $1 AS col", "params": ["it's a trap"]}
    )
    assert "it's a trap" in result


def test_handler_treats_drop_table_shaped_param_as_opaque_data() -> None:
    payload = "'; DROP TABLE users; --"
    result = run_sql_handler(_db_url(), {"query": "SELECT $1 AS col", "params": [payload]})
    assert payload in result
    assert "DROP TABLE" not in result.replace(payload, "")


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before
# ---------------------------------------------------------------------------


def test_handler_runs_a_real_query_with_no_params() -> None:
    result = run_sql_handler(_db_url(), {"query": "SELECT 1 AS one, 2 AS two"})
    assert "one" in result and "two" in result
    assert "1" in result and "2" in result


def test_handler_runs_a_real_query_with_a_legit_param() -> None:
    result = run_sql_handler(
        _db_url(), {"query": "SELECT $1 AS greeting", "params": ["hello world"]}
    )
    assert "hello world" in result


def test_handler_reports_ddl_success_without_a_result_set() -> None:
    # UPDATED (verification batch B3): DDL now needs explicit write approval
    # (allow_write=True — the interactive chat grants it only after a human says
    # yes). Without it the statement is refused, never executed.
    stmt = {"query": "CREATE TEMP TABLE td_run_sql_ddl_test (x int)"}
    assert run_sql_handler(_db_url(), stmt).startswith("[WRITE BLOCKED]")
    assert run_sql_handler(_db_url(), stmt, allow_write=True) == "Query OK"


def test_handler_errors_cleanly_on_missing_database_url() -> None:
    result = run_sql_handler("", {"query": "SELECT 1"})
    assert result == "[ERROR] DATABASE_URL not configured"


def test_handler_errors_cleanly_on_bad_sql() -> None:
    result = run_sql_handler(_db_url(), {"query": "SELECT FROM WHERE garbage"})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_sql_real_dispatch_closes_the_exploit(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    payload = "x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; --"
    result = await agent._execute_tool(
        "run_sql", {"query": "SELECT $1 AS col", "params": [payload]}
    )
    assert payload in result


@pytest.mark.asyncio
async def test_chat_agent_run_sql_real_dispatch_legit_query(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("run_sql", {"query": "SELECT 42 AS answer"})
    assert "42" in result


def test_make_chat_handlers_run_sql_closes_the_exploit(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    payload = "x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; --"
    result = handlers["run_sql"]({"query": "SELECT $1 AS col", "params": [payload]})
    assert payload in result


def test_make_chat_handlers_run_sql_legit_query(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_sql"]({"query": "SELECT 42 AS answer"})
    assert "42" in result
