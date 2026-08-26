"""health_check tool #113 — tool_enhance.md productionization pass
(2026-08-26).

`service` is the only LLM-controlled field and only ever SELECTS a
fixed branch — port/database_url come from server-side settings,
never the LLM — so the usual worktree-escape/flag-collision/shell-
injection classes are structurally impossible for the two already-
correct implementations. Both real findings are on `mon_health_check`,
a genuinely different, broken implementation.

1. A real, severe functionality bug: `mon_health_check` completely
   ignored `service` (the tool's only documented input) and read an
   entirely undocumented `url` field instead — never checking database
   connectivity in any case, contradicting the tool's own description.
2. A real, second-order SSRF surface: since tool schemas are advisory
   to the model, not enforced server-side, a real tool-call payload
   could include an extra, undocumented `url` key that
   `mon_health_check` would use directly as its `curl` target with
   zero validation.

Fixed by fully replacing `mon_health_check` with the shared
`health_check_handler()`, which never reads a `url` field at all.

All tests here use real subprocess calls (`curl`/`pg_isready`) —
nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_monitoring_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.health_check import HEALTH_CHECK_TOOL, health_check_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_health_check_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_health_check_tool_schema() -> None:
    assert HEALTH_CHECK_TOOL["name"] == "health_check"
    assert HEALTH_CHECK_TOOL["input_schema"]["required"] == []  # type: ignore[index]
    assert "url" not in HEALTH_CHECK_TOOL["input_schema"]["properties"]  # type: ignore[index]


def test_health_check_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("health_check") == 1


# ---------------------------------------------------------------------------
# Finding #1 — mon_health_check ignored `service` and never checked DB
# ---------------------------------------------------------------------------


def test_handler_honors_service_backend_excludes_database() -> None:
    result = health_check_handler({"service": "backend"}, port=8000, database_url="x")
    assert "Backend" in result
    assert "Database" not in result


def test_handler_honors_service_db_excludes_backend() -> None:
    result = health_check_handler({"service": "db"}, port=8000, database_url="x")
    assert "Database" in result
    assert "Backend" not in result


def test_handler_service_all_checks_both() -> None:
    result = health_check_handler({"service": "all"}, port=8000, database_url="x")
    assert "Backend" in result
    assert "Database" in result


def test_monitoring_agent_now_genuinely_checks_database(tmp_path: Path) -> None:
    """Proves the real fix: previously mon_health_check ignored
    service entirely and never attempted a database check under any
    circumstances -- now service='db' must produce a Database line."""
    handlers = make_monitoring_agent_handlers(str(tmp_path))
    result = handlers["health_check"]({"service": "db"})
    assert "Database" in result
    assert "Backend" not in result


# ---------------------------------------------------------------------------
# Finding #2 — mon_health_check's undocumented `url` / SSRF surface
# ---------------------------------------------------------------------------


def test_handler_never_accepts_a_url_field(tmp_path: Path) -> None:
    """Even if a real tool-call payload smuggled an extra `url` key
    (schemas are advisory, not enforced), the shared handler must never
    read it -- it has no `url` parameter at all."""
    handlers = make_monitoring_agent_handlers(str(tmp_path))
    result = handlers["health_check"](
        {"service": "backend", "url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert "169.254.169.254" not in result


@pytest.mark.asyncio
async def test_chat_agent_never_accepts_a_url_field(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "health_check",
        {"service": "backend", "url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert "169.254.169.254" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all three real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_returns_real_backend_status(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("health_check", {"service": "backend"})
    assert "Backend" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_monitoring_agent_handlers],
)
def test_both_factories_return_real_status(tmp_path: Path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["health_check"]({})
    assert isinstance(result, str)
    assert result
