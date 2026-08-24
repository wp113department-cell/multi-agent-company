"""find_sql tool #91 — tool_enhance.md productionization pass
(2026-08-24).

Two real, empirically-verified findings across five real
implementations, fixed at the shared `find_sql_handler()` in
`app.tools.filesystem.find_sql`:

1. The same "an external program's own flag parser accepts an
   LLM-controlled positional field" class already established for
   tools #69/#89/#90, on FOUR of the five real implementations
   (`sec_find_sql`, `sq_find_sql`, `find_sql_h`, `chat_agent.py`'s
   dispatch — whose `shlex.quote()` again only protects against SHELL
   metacharacters, not grep's own argv-level flag parsing). Proved
   live: `keyword="-w"` was silently consumed as grep's own flag
   instead of the literal search text.
2. A real functionality bug in `pr_find_sql` (the only pure-Python,
   no-subprocess implementation, never exposed to finding #1): empty
   `keyword` searched only `"SELECT"`, not the full SQL keyword set
   the schema promises ("empty = all SQL"). Proved live: a real
   INSERT statement was invisible to it.

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_performance_reviewer_handlers,
    make_security_reviewer_handlers,
    make_sql_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.find_sql import FIND_SQL_TOOL, validate_find_sql_keyword


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_find_sql_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_find_sql_tool_schema_has_no_required_fields() -> None:
    assert FIND_SQL_TOOL["name"] == "find_sql"
    assert FIND_SQL_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_find_sql_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_sql") == 1


def test_validate_find_sql_keyword_rejects_flag_shaped_values() -> None:
    assert validate_find_sql_keyword("-w") is not None
    assert validate_find_sql_keyword("--include=/etc/passwd") is not None


def test_validate_find_sql_keyword_accepts_legitimate_keywords() -> None:
    assert validate_find_sql_keyword("SELECT") is None
    assert validate_find_sql_keyword("INSERT") is None


# ---------------------------------------------------------------------------
# Finding #1 — flag-collision on `keyword` (four real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_flag_shaped_keyword(tmp_path: Path) -> None:
    (tmp_path / "db.py").write_text('query = "SELECT * FROM users"\n')
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_sql", {"keyword": "-w"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("security_reviewer", make_security_reviewer_handlers),
        ("sql_agent", make_sql_agent_handlers),
    ],
)
def test_grep_based_factories_reject_flag_shaped_keyword(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["find_sql"]({"keyword": "-w"})
    assert "[ERROR]" in result, f"{factory_name} did not reject the flag-shaped keyword"


# ---------------------------------------------------------------------------
# Finding #2 — pr_find_sql empty-keyword functionality bug
# ---------------------------------------------------------------------------


def test_performance_reviewer_empty_keyword_now_finds_all_sql_types(
    tmp_path: Path,
) -> None:
    """Previously defaulted to searching only 'SELECT' — now matches
    the full SQL keyword set the schema promises."""
    (tmp_path / "db.py").write_text('query = "INSERT INTO users VALUES (1)"\n')
    handlers = make_performance_reviewer_handlers(str(tmp_path))
    result = handlers["find_sql"]({})
    assert "INSERT" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all five real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_finds_real_sql_by_keyword(tmp_path: Path) -> None:
    (tmp_path / "db.py").write_text('query = "SELECT * FROM users"\n')
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_sql", {"keyword": "SELECT"})
    assert "SELECT" in result


@pytest.mark.asyncio
async def test_chat_agent_empty_keyword_finds_all_sql(tmp_path: Path) -> None:
    (tmp_path / "db.py").write_text('query = "DELETE FROM users"\n')
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_sql", {})
    assert "DELETE" in result


@pytest.mark.asyncio
async def test_chat_agent_no_match_reports_cleanly(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_sql", {"keyword": "SELECT"})
    assert "No SQL statements found" in result


@pytest.mark.parametrize(
    "factory",
    [
        make_chat_handlers,
        make_security_reviewer_handlers,
        make_sql_agent_handlers,
        make_performance_reviewer_handlers,
    ],
)
def test_all_four_factories_find_real_sql_by_keyword(tmp_path: Path, factory) -> None:
    (tmp_path / "db.py").write_text('query = "SELECT * FROM users"\n')
    handlers = factory(str(tmp_path))
    result = handlers["find_sql"]({"keyword": "SELECT"})
    assert "SELECT" in result
