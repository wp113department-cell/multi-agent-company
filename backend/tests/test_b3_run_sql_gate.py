"""Verification batch B3, items #218/#220 (dangerous commands / DB changes gated).

Proved live before the fix:
* chat's run_sql executed `DELETE FROM t` and `DROP TABLE t` against the platform's OWN
  database with autocommit and NO confirmation (prompt injection into a chat could wipe
  tasks/users/audit/credentials);
* the sql/schema/migration/performance agents' run_sql shelled out to
  `psql <postgresql+asyncpg://...> -c` (psql reads that as a database NAME: it could never
  connect) with no read-only guard — "blocked from DROP/DELETE" was prompt-only;
* a Postgres read-only transaction alone is NOT a sufficient guard: `SET TRANSACTION READ
  WRITE; DELETE ...` and `COMMIT; BEGIN READ WRITE; DELETE ...` execute inside one call.

Real Postgres, real scratch table.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import psycopg2
import pytest

from app.agents.chat_agent import ChatAgent
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database import sql as sqlmod
from app.tools.database.sql import WRITE_BLOCKED, is_read_only_sql, run_sql_handler

TABLE = "b3_gate_probe"

OK_READS = [
    "SELECT 1",
    "select * from t where a = 'x; drop table t'",
    "SELECT 1;",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "EXPLAIN SELECT * FROM t",
    "SHOW server_version",
    "SELECT 'it''s; DROP TABLE t'",
    "SELECT $$; DROP$$",
    "SELECT 1 -- ; DROP TABLE t",
    "/* ; */ SELECT 1",
    'SELECT "drop table" FROM t',
    "VALUES (1),(2)",
    "TABLE users",
    "SELECT updated_at, deleted_at FROM t",
    "SELECT CASE WHEN a THEN 1 ELSE 2 END FROM t",
    "SELECT * FROM t ORDER BY id FETCH FIRST 5 ROWS ONLY",
    "SELECT count(*) FROM information_schema.tables WHERE table_name = 'drop'",
    "SELECT * FROM t WHERE created_at > now() - interval '1 day'",
]
BAD = [
    "DELETE FROM t",
    "DROP TABLE t",
    "SELECT 1; DELETE FROM t",
    "SELECT 1; COMMIT; DELETE FROM t",
    "SET TRANSACTION READ WRITE; DELETE FROM t",
    "COMMIT; BEGIN READ WRITE; DELETE FROM t",
    "UPDATE t SET a=1",
    "INSERT INTO t VALUES (1)",
    "SELECT * INTO newt FROM t",
    "COPY (SELECT 1) TO PROGRAM 'id'",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT nextval('s')",
    "SELECT set_config('transaction_read_only','off',false)",
    "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
    "TRUNCATE t",
    "CREATE TABLE x(i int)",
    "  ",
    "",
    "SELECT lo_import('/etc/passwd')",
    "EXPLAIN ANALYZE DELETE FROM t",
    "SELECT 1 /* x */ ; /* y */ DROP TABLE t",
    "DO $$ BEGIN DELETE FROM t; END $$",
    "CALL p()",
    "GRANT ALL ON t TO x",
    "SELECT 1;;DROP TABLE t",
    "SELECT * FROM t FOR UPDATE",
    "select/**/1;drop table t",
    "SELECT 1\n;\nDROP TABLE t",
    "sElEcT 1; dRoP tAbLe t",
]


@pytest.mark.parametrize("q", OK_READS)
def test_legitimate_reads_are_classified_read_only(q) -> None:
    assert is_read_only_sql(q), q


@pytest.mark.parametrize("q", BAD)
def test_anything_that_can_write_or_stack_statements_is_not_read_only(q) -> None:
    assert not is_read_only_sql(q), q


def _dsn() -> str:
    import re

    return re.sub(r"^postgresql\+\w+://", "postgresql://", get_settings().database_url)


def _exec(sql: str) -> None:
    c = psycopg2.connect(_dsn())
    c.autocommit = True
    c.cursor().execute(sql)
    c.close()


def _rows() -> int | None:
    c = psycopg2.connect(_dsn())
    try:
        cur = c.cursor()
        cur.execute("select to_regclass(%s)", (f"public.{TABLE}",))
        if cur.fetchone()[0] is None:
            return None
        cur.execute(f"select count(*) from {TABLE}")
        return cur.fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def table():
    _exec(
        f"drop table if exists {TABLE}; create table {TABLE}(id int, note text);"
        f"insert into {TABLE} values (1,'a'),(2,'b'),(3,'c')"
    )
    yield TABLE
    _exec(f"drop table if exists {TABLE}")


def _run(q: str, **kw):
    return run_sql_handler(get_settings().database_url, {"query": q}, **kw)


def test_reads_work_against_the_real_database_with_the_asyncpg_url(table) -> None:
    assert "3" in _run(f"SELECT count(*) FROM {table}")
    out = run_sql_handler(
        get_settings().database_url,
        {"query": f"SELECT note FROM {table} WHERE id = $1", "params": ["2"]},
    )
    assert "b" in out and "[ERROR]" not in out
    assert _rows() == 3, "a read must never modify anything"


@pytest.mark.parametrize(
    "template",
    [
        "DELETE FROM {t}",
        "DROP TABLE {t}",
        "TRUNCATE {t}",
        "UPDATE {t} SET note = 'x'",
        "SELECT 1; DELETE FROM {t}",
        "SELECT 1; COMMIT; DELETE FROM {t}",
        "SET TRANSACTION READ WRITE; DELETE FROM {t}",
        "COMMIT; BEGIN READ WRITE; DELETE FROM {t}; COMMIT",
        "WITH d AS (DELETE FROM {t} RETURNING *) SELECT count(*) FROM d",
        "EXPLAIN ANALYZE DELETE FROM {t}",
    ],
)
def test_destructive_statements_are_refused_and_change_nothing(table, template) -> None:
    out = _run(template.format(t=table))
    assert out.startswith(WRITE_BLOCKED), out
    assert _rows() == 3


def test_the_read_only_transaction_is_an_independent_second_layer(
    table, monkeypatch
) -> None:
    """Even if the classifier were fooled, the connection itself refuses to write."""
    monkeypatch.setattr(sqlmod, "is_read_only_sql", lambda q: True)
    out = _run(f"DELETE FROM {table}")
    assert "[ERROR]" in out and "read-only" in out.lower()
    assert _rows() == 3


def test_an_approved_write_still_works(table) -> None:
    assert "3 row(s) affected" in _run(f"DELETE FROM {table}", allow_write=True)
    assert _rows() == 0
    assert _run(f"DROP TABLE {table}", allow_write=True).startswith("Query OK")
    assert _rows() is None


# --------------------------- chat approval flow ---------------------------


def _chat() -> ChatAgent:
    return ChatAgent(ChatSession(session_id="b3_sql_gate", repo_path="/tmp"))


def _call(agent: ChatAgent, q: str) -> str:
    return asyncio.run(agent._execute_tool("run_sql", {"query": q}))


def test_chat_denied_write_asks_once_and_changes_nothing(table) -> None:
    a = _chat()
    a._confirm = AsyncMock(return_value=False)
    out = _call(a, f"DROP TABLE {table}")
    assert out.startswith("[DENIED]") and a._confirm.await_count == 1
    assert "DROP TABLE" in a._confirm.await_args.kwargs["details"]
    assert _rows() == 3


def test_chat_approved_write_executes(table) -> None:
    a = _chat()
    a._confirm = AsyncMock(return_value=True)
    assert "3 row(s) affected" in _call(a, f"DELETE FROM {table}")
    assert a._confirm.await_count == 1 and _rows() == 0


def test_chat_reads_never_prompt(table) -> None:
    a = _chat()
    a._confirm = AsyncMock(return_value=False)
    assert "3" in _call(a, f"SELECT count(*) FROM {table}")
    assert a._confirm.await_count == 0


# ---------------------- headless agents (no human to ask) ------------------


@pytest.mark.parametrize(
    "factory",
    [
        "make_sql_agent_handlers",
        "make_schema_agent_handlers",
        "make_migration_agent_handlers",
        "make_performance_reviewer_handlers",
        "make_chat_handlers",
    ],
)
def test_headless_agents_can_read_but_never_write(table, factory, tmp_path) -> None:
    from app.agents import tools as tools_mod

    fn = getattr(tools_mod, factory, None)
    if fn is None:
        pytest.skip(f"{factory} not found")
    handlers = fn(str(tmp_path))
    if "run_sql" not in handlers:
        pytest.skip(f"{factory} has no run_sql")
    assert "3" in handlers["run_sql"]({"query": f"SELECT count(*) FROM {table}"})
    out = handlers["run_sql"]({"query": f"DROP TABLE {table}"})
    assert WRITE_BLOCKED in out, out
    assert _rows() == 3
