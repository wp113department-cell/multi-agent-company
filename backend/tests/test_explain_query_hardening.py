"""explain_query tool #98 — tool_enhance.md productionization pass
(2026-08-25).

Real, empirically-verified finding (severe — this tool's own schema
explicitly promises "Read-only (EXPLAIN does not modify data)", proved
FALSE two separate ways against the real project database, using a
disposable table never part of real project data): (1) statement
stacking — a query value closing with a second, attacker-controlled
statement genuinely executed it, same multi-statement mechanism as
tools #15/#96; (2) a single, non-stacked non-SELECT query (e.g. a bare
INSERT) is genuinely EXECUTED by `EXPLAIN ANALYZE` — documented core
Postgres behavior this tool never guarded against.

Fixed via a real, two-part validator: reject any embedded semicolon
(after stripping at most one purely-trailing one), and reject any
query that doesn't start with SELECT/WITH.

These tests require a real, reachable PostgreSQL database (DATABASE_URL)
— skipped otherwise, matching this codebase's existing convention for
DB-dependent tests.
"""

from __future__ import annotations

import re

import psycopg2
import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_performance_reviewer_handlers,
    make_sql_agent_handlers,
)
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database.explain_query import (
    EXPLAIN_QUERY_TOOL,
    _validate_explain_query,
    explain_query_handler,
)

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)

PROOF_TABLE = "explain_query_hardening_proof"


def _db_url() -> str:
    return get_settings().database_url


def _psycopg2_dsn() -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", _db_url())


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_explain_query_hardening", repo_path=repo)
    return ChatAgent(session)


@pytest.fixture
def proof_table():
    dsn = _psycopg2_dsn()
    conn = psycopg2.connect(dsn, connect_timeout=10)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"CREATE TABLE IF NOT EXISTS {PROOF_TABLE} (id int)")
    cur.execute(f"DELETE FROM {PROOF_TABLE}")
    yield
    cur.execute(f"DROP TABLE IF EXISTS {PROOF_TABLE}")
    conn.close()


def _row_count(cur) -> int:
    cur.execute(f"SELECT count(*) FROM {PROOF_TABLE}")
    return cur.fetchone()[0]


def test_explain_query_tool_schema() -> None:
    assert EXPLAIN_QUERY_TOOL["name"] == "explain_query"
    assert EXPLAIN_QUERY_TOOL["input_schema"]["required"] == ["query"]  # type: ignore[index]


def test_explain_query_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("explain_query") == 1


# ---------------------------------------------------------------------------
# Pure validator unit tests (no DB needed)
# ---------------------------------------------------------------------------


def test_validator_accepts_plain_select() -> None:
    cleaned, error = _validate_explain_query("SELECT 1")
    assert error is None
    assert cleaned == "SELECT 1"


def test_validator_strips_one_trailing_semicolon() -> None:
    cleaned, error = _validate_explain_query("SELECT 1;")
    assert error is None
    assert cleaned == "SELECT 1"


def test_validator_accepts_with_cte() -> None:
    cleaned, error = _validate_explain_query("WITH x AS (SELECT 1) SELECT * FROM x")
    assert error is None


def test_validator_rejects_embedded_semicolon() -> None:
    _, error = _validate_explain_query("SELECT 1; SELECT 2")
    assert error is not None
    assert "single statement" in error


def test_validator_rejects_non_select() -> None:
    _, error = _validate_explain_query("INSERT INTO t VALUES (1)")
    assert error is not None
    assert "SELECT/WITH" in error


def test_validator_rejects_delete() -> None:
    _, error = _validate_explain_query("DELETE FROM t")
    assert error is not None


# ---------------------------------------------------------------------------
# Finding #1 — statement stacking (real DB proof)
# ---------------------------------------------------------------------------


def test_handler_rejects_stacked_mutating_statement(proof_table) -> None:
    payload = f"SELECT 1; INSERT INTO {PROOF_TABLE} VALUES (999)"
    result = explain_query_handler(_db_url(), {"query": payload})
    assert result.startswith("[ERROR]")

    dsn = _psycopg2_dsn()
    conn = psycopg2.connect(dsn, connect_timeout=10)
    conn.autocommit = True
    cur = conn.cursor()
    assert _row_count(cur) == 0
    conn.close()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_rejects_stacked_statement(tmp_path, proof_table) -> None:
    agent = _agent(str(tmp_path))
    payload = f"SELECT 1; INSERT INTO {PROOF_TABLE} VALUES (999)"
    result = await agent._execute_tool("explain_query", {"query": payload})
    assert result.startswith("[ERROR]")


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("sql_agent", make_sql_agent_handlers),
        ("performance_reviewer", make_performance_reviewer_handlers),
    ],
)
def test_all_three_factories_reject_stacked_statement(
    tmp_path, factory_name: str, factory, proof_table
) -> None:
    handlers = factory(str(tmp_path))
    payload = f"SELECT 1; INSERT INTO {PROOF_TABLE} VALUES (999)"
    result = handlers["explain_query"]({"query": payload})
    assert result.startswith("[ERROR]"), f"{factory_name} did not reject the stacked statement"


# ---------------------------------------------------------------------------
# Finding #2 — single non-SELECT statement (real DB proof)
# ---------------------------------------------------------------------------


def test_handler_rejects_single_insert_statement(proof_table) -> None:
    result = explain_query_handler(
        _db_url(), {"query": f"INSERT INTO {PROOF_TABLE} VALUES (1)"}
    )
    assert result.startswith("[ERROR]")

    dsn = _psycopg2_dsn()
    conn = psycopg2.connect(dsn, connect_timeout=10)
    conn.autocommit = True
    cur = conn.cursor()
    assert _row_count(cur) == 0
    conn.close()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all four real
# access paths
# ---------------------------------------------------------------------------


def test_handler_runs_a_real_select() -> None:
    result = explain_query_handler(_db_url(), {"query": "SELECT 1"})
    assert "Result" in result or "Execution Time" in result


def test_handler_accepts_trailing_semicolon() -> None:
    result = explain_query_handler(_db_url(), {"query": "SELECT 1;"})
    assert not result.startswith("[ERROR]")


def test_handler_errors_cleanly_on_missing_database_url() -> None:
    result = explain_query_handler("", {"query": "SELECT 1"})
    assert result == "[ERROR] DATABASE_URL not configured"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_runs_a_real_select(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("explain_query", {"query": "SELECT 1"})
    assert not result.startswith("[ERROR]")


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_sql_agent_handlers, make_performance_reviewer_handlers],
)
def test_all_three_factories_run_a_real_select(tmp_path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["explain_query"]({"query": "SELECT 1"})
    assert not result.startswith("[ERROR]")
