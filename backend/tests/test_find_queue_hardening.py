"""find_queue tool #139 — tool_enhance.md productionization pass
(2026-09-11).

Two real, empirically-verified findings, on the one real
implementation (`find_queue_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. Most severe: a worktree-boundary escape via `repo_path` — a genuine
   FULL FILE CONTENT disclosure oracle (not just filenames).
   `_rp = str(inp.get("repo_path", repo_path))` used the LLM-
   controlled value completely unanchored, with no join against the
   real worktree root at all. Proved live: real matching CONTENT LINES
   (not just filenames) were genuinely disclosed from a directory
   entirely outside the intended worktree.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `find_queue_handler()` using
`check_path_in_worktree()` on `repo_path`. As a side effect, a
relative `repo_path` override is now correctly anchored to the real
worktree root — the original never joined it to anything, so its
behavior depended on the running process's own cwd rather than the
intended repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.find_queue import FIND_QUEUE_TOOL, find_queue_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_find_queue_hardening", repo_path=repo)
    return ChatAgent(session)


def test_find_queue_tool_schema() -> None:
    assert FIND_QUEUE_TOOL["name"] == "find_queue"
    assert FIND_QUEUE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_find_queue_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_queue") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape full file content disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_repo_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("class MySecretQueue:\n    pass\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["find_queue"]({"repo_path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "MySecretQueue" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("class MySecretQueue:\n    pass\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("find_queue", {"repo_path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "MySecretQueue" not in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("class MySecretQueue:\n    pass\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = find_queue_handler(str(repo), {"repo_path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "q.py").write_text("import asyncio\nq = asyncio.Queue()\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("find_queue", {})
    assert "Unknown tool" not in result
    assert "asyncio.Queue" in result


# ---------------------------------------------------------------------------
# Regression + correctness improvement — legitimate usage must keep
# working on both real access paths, and a relative repo_path now
# genuinely scopes to the real intended subdirectory
# ---------------------------------------------------------------------------


def test_handler_finds_a_real_match_with_default_repo_path(tmp_path: Path) -> None:
    (tmp_path / "q.py").write_text("import asyncio\nq = asyncio.Queue()\n")
    result = find_queue_handler(str(tmp_path), {})
    assert "asyncio.Queue" in result


def test_handler_reports_no_matches(tmp_path: Path) -> None:
    (tmp_path / "plain.py").write_text("x = 1\n")
    result = find_queue_handler(str(tmp_path), {})
    assert result == "No queue patterns found."


def test_handler_excludes_venv_and_node_modules(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "lib.py").write_text("class Queue:\n    pass\n")
    (tmp_path / "real.py").write_text("import asyncio\nq = asyncio.Queue()\n")
    result = find_queue_handler(str(tmp_path), {})
    assert ".venv/" not in result
    assert "real.py" in result


def test_handler_relative_repo_path_correctly_scopes_to_subdirectory(
    tmp_path: Path,
) -> None:
    """The correctness improvement: the original never anchored a
    relative repo_path to the real worktree at all."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "worker.py").write_text("import celery\n")
    (tmp_path / "outer.py").write_text("import asyncio\nq = asyncio.Queue()\n")

    result = find_queue_handler(str(tmp_path), {"repo_path": "sub"})
    assert "worker.py" in result
    assert "outer.py" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_finds_a_real_match(tmp_path: Path) -> None:
    (tmp_path / "q.py").write_text("import asyncio\nq = asyncio.Queue()\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("find_queue", {})
    assert "asyncio.Queue" in result
