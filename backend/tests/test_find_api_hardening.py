"""find_api tool #89 — tool_enhance.md productionization pass
(2026-08-24).

Same "an external program's own flag parser accepts an LLM-controlled
positional field" class first found in tool #59 (`run_make`)/tool #69
(`search_code`), on ALL FOUR real implementations (including
`chat_agent.py`'s dispatch — its `shlex.quote()` defends against SHELL
metacharacter injection only, not grep's own argv-level flag parsing),
fixed at the shared `find_api_handler()` in
`app.tools.filesystem.find_api`.

`name` was a bare positional argv element with no `--` separator.
Proved live: `name="-l"` was silently consumed as grep's own flag
instead of the literal search text, producing a misleadingly-confident
"no results" answer.

A secondary, non-security finding: two implementations searched
`node_modules`/`.venv`/`__pycache__` and only `.py` files; the other
two (the more complete ones) excluded those directories and also
searched `.ts` — all four are now unified onto the more complete
behavior.

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_api_docs_agent_handlers,
    make_chat_handlers,
    make_security_reviewer_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.find_api import FIND_API_TOOL, validate_find_api_name


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_find_api_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_find_api_tool_schema_has_no_required_fields() -> None:
    assert FIND_API_TOOL["name"] == "find_api"
    assert FIND_API_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_find_api_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_api") == 1


def test_validate_find_api_name_rejects_flag_shaped_values() -> None:
    assert validate_find_api_name("-l") is not None
    assert validate_find_api_name("--include=/etc/passwd") is not None


def test_validate_find_api_name_accepts_legitimate_names() -> None:
    assert validate_find_api_name("get_users") is None
    assert validate_find_api_name("/api/users") is None


# ---------------------------------------------------------------------------
# Finding — flag-collision on `name` (all four real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_flag_shaped_name(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('@app.get("-l")\ndef weird():\n    pass\n')
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_api", {"name": "-l"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("security_reviewer", make_security_reviewer_handlers),
        ("api_docs_agent", make_api_docs_agent_handlers),
    ],
)
def test_all_three_factories_reject_flag_shaped_name(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["find_api"]({"name": "-l"})
    assert "[ERROR]" in result, f"{factory_name} did not reject the flag-shaped name"


# ---------------------------------------------------------------------------
# Secondary finding — node_modules/.venv/__pycache__ exclusion + .ts
# support, unified across all four
# ---------------------------------------------------------------------------


def _repo_with_node_modules_junk(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text('@app.get("/users")\ndef get_users():\n    pass\n')
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "junk.py").write_text('@app.get("/junk")\ndef junk():\n    pass\n')
    return tmp_path


@pytest.mark.asyncio
async def test_chat_agent_excludes_node_modules(tmp_path: Path) -> None:
    _repo_with_node_modules_junk(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_api", {})
    assert "junk" not in result
    assert "/users" in result


def test_security_reviewer_now_excludes_node_modules_too(tmp_path: Path) -> None:
    """Previously searched node_modules — now unified onto the more
    complete exclusion behavior."""
    _repo_with_node_modules_junk(tmp_path)
    handlers = make_security_reviewer_handlers(str(tmp_path))
    result = handlers["find_api"]({})
    assert "junk" not in result
    assert "/users" in result


def test_api_docs_agent_now_excludes_node_modules_too(tmp_path: Path) -> None:
    _repo_with_node_modules_junk(tmp_path)
    handlers = make_api_docs_agent_handlers(str(tmp_path))
    result = handlers["find_api"]({})
    assert "junk" not in result
    assert "/users" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all four real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_finds_real_api_by_name(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('@app.get("/users")\ndef get_users():\n    pass\n')
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_api", {"name": "get_users"})
    assert "get_users" in result


@pytest.mark.asyncio
async def test_chat_agent_empty_name_finds_all_route_handlers(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        '@app.post("/items")\ndef create_item():\n    pass\n'
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_api", {})
    assert '@app.post("/items")' in result


@pytest.mark.asyncio
async def test_chat_agent_no_match_reports_cleanly(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_api", {"name": "nonexistent_endpoint"})
    assert "No API definitions found" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_security_reviewer_handlers, make_api_docs_agent_handlers],
)
def test_all_three_factories_find_real_api_by_name(tmp_path: Path, factory) -> None:
    (tmp_path / "app.py").write_text('@app.get("/users")\ndef get_users():\n    pass\n')
    handlers = factory(str(tmp_path))
    result = handlers["find_api"]({"name": "get_users"})
    assert "get_users" in result
