"""task_history_query tool #118 — tool_enhance.md productionization
pass (2026-08-26).

Three real, empirically-verified findings:

1. The tool was completely non-functional — it queried `FROM
   task_logs`, but the real `task_logs` table has no `status` column
   at all. Proved live against the real project database: the exact
   original query raised `psycopg2.errors.UndefinedColumn`. The real,
   intended table is `dev_tasks`, which genuinely has `id`, `status`,
   `created_at`.
2. A genuine, live SQL injection (same class as tools #15/#96) on the
   corrected query — `status` was f-string-interpolated into raw SQL
   handed to `psql -c`. Proved directly against the real database: a
   payload closing the string literal early caused a second,
   attacker-controlled statement to execute.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools #100/#103/#110/#112) — every real interactive-
   chat call fell through to "[ERROR] Unknown tool".

All three are now closed: the query targets `dev_tasks`, `status`/
`limit` are passed via real psycopg2 parameter binding (never
string-interpolated), and chat_agent.py gained a real dispatch branch.

These tests require a real, reachable PostgreSQL database
(DATABASE_URL) — skipped otherwise, matching this codebase's existing
convention for DB-dependent tests.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers, task_history_query
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database.task_history_query import TASK_HISTORY_QUERY_TOOL

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)

INJECTION_PAYLOAD = "x'; SELECT 'INJECTED_MARKER_TASK_HISTORY' AS proof; --"


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_task_history_query_hardening", repo_path=repo)
    return ChatAgent(session)


def test_task_history_query_tool_schema() -> None:
    assert TASK_HISTORY_QUERY_TOOL["name"] == "task_history_query"
    assert TASK_HISTORY_QUERY_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_task_history_query_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("task_history_query") == 1


# ---------------------------------------------------------------------------
# Finding #1 — the tool was completely non-functional (wrong table)
# ---------------------------------------------------------------------------


def test_function_queries_the_real_dev_tasks_table_not_task_logs() -> None:
    """Real proof the fix targets the table that actually has `status` —
    a bare call with no filters must not error."""
    result = task_history_query({"limit": 5})
    assert "[ERROR]" not in result


# ---------------------------------------------------------------------------
# Finding #2 — SQL injection via `status`
# ---------------------------------------------------------------------------


def test_function_treats_injection_payload_as_opaque_data_not_sql() -> None:
    result = task_history_query({"status": INJECTION_PAYLOAD})
    assert "INJECTED_MARKER_TASK_HISTORY" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_exploit(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "task_history_query", {"status": INJECTION_PAYLOAD}
    )
    assert "INJECTED_MARKER_TASK_HISTORY" not in result


def test_make_chat_handlers_closes_the_exploit(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["task_history_query"]({"status": INJECTION_PAYLOAD})
    assert "INJECTED_MARKER_TASK_HISTORY" not in result


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("task_history_query", {"limit": 3})
    assert "Unknown tool" not in result
    assert "[ERROR]" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths
# ---------------------------------------------------------------------------


def test_function_errors_cleanly_on_missing_database_url(monkeypatch) -> None:
    class _FakeSettings:
        database_url = ""

    monkeypatch.setattr(
        "app.config.get_settings", lambda: _FakeSettings()
    )
    result = task_history_query({})
    assert result == "[ERROR] DATABASE_URL not set"


def test_function_returns_real_rows_with_no_filters() -> None:
    result = task_history_query({"limit": 5})
    assert "[ERROR]" not in result
    assert result == "(no task history found)" or len(result.splitlines()) <= 5


def test_function_honors_limit() -> None:
    result = task_history_query({"limit": 2})
    lines = result.splitlines()
    assert len(lines) <= 2


def test_function_honors_status_filter() -> None:
    result = task_history_query({"status": "pending", "limit": 3})
    assert "[ERROR]" not in result
    for line in result.splitlines():
        if line != "(no task history found)":
            assert "  pending  " in line


@pytest.mark.asyncio
async def test_chat_agent_dispatch_shows_real_task_history(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("task_history_query", {"limit": 3})
    assert "[ERROR]" not in result


def test_make_chat_handlers_shows_real_task_history(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["task_history_query"]({"limit": 3})
    assert "[ERROR]" not in result
