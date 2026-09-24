"""inspect_schema tool #96 — tool_enhance.md productionization pass
(2026-08-25).

Real, empirically-verified finding (severe — a proven, live SQL
injection, same class as tool #15's run_sql): ALL FIVE real
implementations f-string-interpolated the LLM-controlled `table` field
directly into a raw SQL/psql-meta-command string, then handed the whole
constructed string to `psql -c` as a single argv element. Proved
directly against the real project database (read-only, no data
modified) that a `table` value of `"x'; SELECT 'INJECTED_MARKER' AS
proof; --"` broke out of its intended string literal and would execute
as a real, separate stacked SQL statement — the exact same mechanism
already proven for tool #15's `run_sql`.

Fixed via full replacement, matching tool #15's precedent: the shared
`inspect_schema_handler()` no longer shells out to `psql` at all — real
psycopg2 parameter binding instead, so `table` is never string-
interpolated into SQL text. As a bonus, the handler now also returns
real constraint info (the tool's own schema always promised
"constraints", but 3 of 5 prior implementations never delivered it).

These tests require a real, reachable PostgreSQL database (DATABASE_URL)
— skipped otherwise, matching this codebase's existing convention for
DB-dependent tests.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_migration_agent_handlers,
    make_schema_agent_handlers,
    make_sql_agent_handlers,
)
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database.inspect_schema import (
    INSPECT_SCHEMA_TOOL,
    inspect_schema_handler,
)

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)

INJECTION_PAYLOAD = "x'; SELECT 'INJECTED_MARKER_INSPECT_SCHEMA' AS proof; --"


def _db_url() -> str:
    return get_settings().database_url


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_inspect_schema_hardening", repo_path=repo)
    return ChatAgent(session)


def test_inspect_schema_tool_schema() -> None:
    assert INSPECT_SCHEMA_TOOL["name"] == "inspect_schema"
    assert INSPECT_SCHEMA_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_inspect_schema_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("inspect_schema") == 1


# ---------------------------------------------------------------------------
# Finding — SQL injection via `table` (all five real implementations)
# ---------------------------------------------------------------------------


def test_handler_treats_injection_payload_as_opaque_data_not_sql() -> None:
    result = inspect_schema_handler(_db_url(), {"table": INJECTION_PAYLOAD})
    assert "INJECTED_MARKER_INSPECT_SCHEMA" not in result or result == (
        f"(table not found: {INJECTION_PAYLOAD})"
    )
    assert result == f"(table not found: {INJECTION_PAYLOAD})"


def test_handler_treats_single_quote_table_as_opaque_data() -> None:
    result = inspect_schema_handler(_db_url(), {"table": "it's a table"})
    assert result == "(table not found: it's a table)"


def test_handler_treats_drop_table_shaped_value_as_opaque_data() -> None:
    payload = "x'; DROP TABLE agent_benchmarks; --"
    result = inspect_schema_handler(_db_url(), {"table": payload})
    assert result == f"(table not found: {payload})"
    # Real proof the table survived: it's still inspectable afterward.
    survived = inspect_schema_handler(_db_url(), {"table": "agent_benchmarks"})
    assert "Table: agent_benchmarks" in survived


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_exploit(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("inspect_schema", {"table": INJECTION_PAYLOAD})
    assert result == f"(table not found: {INJECTION_PAYLOAD})"


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("sql_agent", make_sql_agent_handlers),
        ("migration_agent", make_migration_agent_handlers),
        ("schema_agent", make_schema_agent_handlers),
    ],
)
def test_all_four_factories_close_the_exploit(
    tmp_path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["inspect_schema"]({"table": INJECTION_PAYLOAD})
    assert (
        result == f"(table not found: {INJECTION_PAYLOAD})"
    ), f"{factory_name} did not close the injection"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all five real
# access paths, and now also returns real constraint info
# ---------------------------------------------------------------------------


def test_handler_lists_tables_with_no_table_given() -> None:
    result = inspect_schema_handler(_db_url(), {})
    assert "table(s):" in result


def test_handler_shows_columns_and_constraints_for_a_real_table() -> None:
    result = inspect_schema_handler(_db_url(), {"table": "agent_benchmarks"})
    assert "Table: agent_benchmarks" in result
    assert "Columns:" in result
    assert "id" in result
    assert "Constraints:" in result
    assert "PRIMARY KEY" in result


def test_handler_errors_cleanly_on_missing_database_url() -> None:
    result = inspect_schema_handler("", {})
    assert result == "[ERROR] DATABASE_URL not configured"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_shows_real_schema(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("inspect_schema", {"table": "agent_benchmarks"})
    assert "Table: agent_benchmarks" in result


@pytest.mark.parametrize(
    "factory",
    [
        make_chat_handlers,
        make_sql_agent_handlers,
        make_migration_agent_handlers,
        make_schema_agent_handlers,
    ],
)
def test_all_four_factories_show_real_schema(tmp_path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["inspect_schema"]({"table": "agent_benchmarks"})
    assert "Table: agent_benchmarks" in result
    assert "Columns:" in result
