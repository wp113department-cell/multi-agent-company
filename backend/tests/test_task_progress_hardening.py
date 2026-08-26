"""task_progress tool #119 — tool_enhance.md productionization pass
(2026-08-26).

Two real, empirically-verified findings, on THREE real implementations
(`mon_task_progress` in `make_monitoring_agent_handlers`,
`task_progress_h` inside `make_chat_handlers`, and `chat_agent.py`'s
own dispatch):

1. The tool was completely non-functional on this host — every real
   call shelled out to the `psql` CLI, which isn't installed here.
   Proved live: all three real call sites returned an error
   (`[ERROR] psql not found` / `FileNotFoundError` /
   `/bin/sh: 1: psql: not found`).
2. `mon_task_progress` silently ignored the schema's own documented
   `limit` field, hardcoding `LIMIT 10` regardless of the caller's
   input.

Both are now closed via a shared `task_progress_handler()` using real
psycopg2 parameter binding (no `psql` subprocess at all), used
identically by all three real call sites.

These tests require a real, reachable PostgreSQL database
(DATABASE_URL) — skipped otherwise, matching this codebase's existing
convention for DB-dependent tests.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_monitoring_agent_handlers,
    task_progress_handler,
)
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database.task_progress import TASK_PROGRESS_TOOL

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_task_progress_hardening", repo_path=repo)
    return ChatAgent(session)


def test_task_progress_tool_schema() -> None:
    assert TASK_PROGRESS_TOOL["name"] == "task_progress"
    assert TASK_PROGRESS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_task_progress_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("task_progress") == 1


# ---------------------------------------------------------------------------
# Finding #1 — the tool was completely non-functional (psql missing)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_monitoring_agent_handlers", make_monitoring_agent_handlers),
        ("make_chat_handlers", make_chat_handlers),
    ],
)
def test_all_factories_genuinely_work_without_psql(
    tmp_path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["task_progress"]({"limit": 3})
    assert "[ERROR]" not in result, f"{factory_name} still broken: {result}"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_genuinely_works_without_psql(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("task_progress", {"limit": 3})
    assert "[ERROR]" not in result
    assert "psql" not in result.lower()


# ---------------------------------------------------------------------------
# Finding #2 — mon_task_progress now honors `limit`
# ---------------------------------------------------------------------------


def test_mon_task_progress_now_honors_limit(tmp_path) -> None:
    handlers = make_monitoring_agent_handlers(str(tmp_path))
    result = handlers["task_progress"]({"limit": 2})
    lines = [line for line in result.splitlines() if line != "(no tasks)"]
    assert len(lines) <= 2


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths, including a specific task_id lookup and invalid input
# ---------------------------------------------------------------------------


def test_handler_errors_cleanly_on_invalid_task_id() -> None:
    result = task_progress_handler({"task_id": "not_a_number"})
    assert result == "[ERROR] Invalid task_id: 'not_a_number'"


def test_handler_returns_a_specific_task_when_task_id_given() -> None:
    listing = task_progress_handler({"limit": 1})
    if listing == "(no tasks)":
        pytest.skip("no dev_tasks rows to test against")
    first_id = int(listing.splitlines()[0].split()[0])
    result = task_progress_handler({"task_id": first_id})
    assert result.splitlines()[0].startswith(f"{first_id}  ")


@pytest.mark.parametrize(
    "factory",
    [make_monitoring_agent_handlers, make_chat_handlers],
)
def test_all_factories_show_real_task_progress(tmp_path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["task_progress"]({"limit": 5})
    assert "[ERROR]" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_shows_real_task_progress(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("task_progress", {"limit": 5})
    assert "[ERROR]" not in result
