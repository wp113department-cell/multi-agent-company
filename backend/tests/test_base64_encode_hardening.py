"""base64_encode tool #122 — tool_enhance.md productionization pass
(2026-08-26).

Two real, empirically-verified findings, on the one real
implementation (`base64_encode_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A worktree-boundary escape that is a genuine ARBITRARY FILE READ —
   `root / path` was never validated. Proved live: an absolute `path`
   outside the intended worktree was genuinely read and base64-encoded
   (a real disclosure primitive, trivially decodable).
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools #100/#103/#110/#112/#118/#120) — every real
   interactive-chat call fell through to "[ERROR] Unknown tool".

Both are now closed via a shared `base64_encode_handler()` using
`check_path_in_worktree()` on `path`, used by both real access paths.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.base64_encode import (
    BASE64_ENCODE_TOOL,
    base64_encode_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_base64_encode_hardening", repo_path=repo)
    return ChatAgent(session)


def test_base64_encode_tool_schema() -> None:
    assert BASE64_ENCODE_TOOL["name"] == "base64_encode"
    assert BASE64_ENCODE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_base64_encode_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("base64_encode") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file read
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET_OUTSIDE_WORKTREE")

    handlers = make_chat_handlers(str(repo))
    result = handlers["base64_encode"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET_OUTSIDE_WORKTREE")

    agent = _agent(str(repo))
    result = await agent._execute_tool("base64_encode", {"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_handler_closes_path_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET_OUTSIDE_WORKTREE")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = base64_encode_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("base64_encode", {"text": "hello"})
    assert "Unknown tool" not in result
    assert result == base64.b64encode(b"hello").decode("ascii")


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths (text encode/decode, file encode)
# ---------------------------------------------------------------------------


def test_handler_encodes_text(tmp_path: Path) -> None:
    result = base64_encode_handler(tmp_path, str(tmp_path), {"text": "hello"})
    assert result == "aGVsbG8="


def test_handler_decodes_text(tmp_path: Path) -> None:
    result = base64_encode_handler(
        tmp_path, str(tmp_path), {"text": "aGVsbG8=", "decode": True}
    )
    assert result == "hello"


def test_handler_encodes_a_real_file(tmp_path: Path) -> None:
    target = tmp_path / "good.txt"
    target.write_text("inside content")
    result = base64_encode_handler(tmp_path, str(tmp_path), {"path": "good.txt"})
    assert base64.b64decode(result).decode() == "inside content"


def test_handler_errors_cleanly_with_no_text_or_path(tmp_path: Path) -> None:
    result = base64_encode_handler(tmp_path, str(tmp_path), {})
    assert result == "[ERROR] Provide either text or path"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_encodes_a_real_file(tmp_path: Path) -> None:
    target = tmp_path / "good.txt"
    target.write_text("inside content")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("base64_encode", {"path": "good.txt"})
    assert base64.b64decode(result).decode() == "inside content"
