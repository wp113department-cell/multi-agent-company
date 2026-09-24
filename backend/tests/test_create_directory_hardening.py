"""create_directory tool #131 — tool_enhance.md productionization pass
(2026-08-26).

Worktree-boundary validation was ALREADY correct on the one real
implementation (`create_directory_h` inside `make_chat_handlers`) —
confirmed by direct inspection and re-verified live below, not
assumed.

One real finding — advertised but never dispatched, on the
interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130. `create_directory`
is in CHAT_TOOLS and registered in `make_chat_handlers()`'s handlers
dict, but `chat_agent.py`'s `_execute_tool()` had no dispatch branch —
every real interactive-chat call fell through to "[ERROR] Unknown
tool".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.create_directory import (
    CREATE_DIRECTORY_TOOL,
    create_directory_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_create_directory_hardening", repo_path=repo)
    return ChatAgent(session)


def test_create_directory_tool_schema() -> None:
    assert CREATE_DIRECTORY_TOOL["name"] == "create_directory"
    assert CREATE_DIRECTORY_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_create_directory_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("create_directory") == 1


# ---------------------------------------------------------------------------
# Finding — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("create_directory", {"path": "newdir"})
    assert "Unknown tool" not in result
    assert (tmp_path / "newdir").is_dir()


# ---------------------------------------------------------------------------
# Regression — worktree validation (already correct) must keep
# working, and legitimate usage must keep working, on both real
# access paths
# ---------------------------------------------------------------------------


def test_make_chat_handlers_still_rejects_protected_path(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["create_directory"]({"path": ".env"})
    assert "[POLICY DENIED]" in result
    assert not (tmp_path / ".env").is_dir()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_rejects_protected_path(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("create_directory", {"path": ".env"})
    assert "[POLICY DENIED]" in result


def test_handler_creates_nested_directories(tmp_path: Path) -> None:
    result = create_directory_handler(
        tmp_path, str(tmp_path), {"path": "new/nested/dir"}
    )
    assert result == "Created directory: new/nested/dir"
    assert (tmp_path / "new" / "nested" / "dir").is_dir()


def test_handler_is_idempotent(tmp_path: Path) -> None:
    inp = {"path": "already/exists"}
    first = create_directory_handler(tmp_path, str(tmp_path), inp)
    second = create_directory_handler(tmp_path, str(tmp_path), inp)
    assert first == second == "Created directory: already/exists"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_creates_nested_directories(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("create_directory", {"path": "new/nested/dir"})
    assert result == "Created directory: new/nested/dir"
    assert (tmp_path / "new" / "nested" / "dir").is_dir()
