"""read_file tool #65 — tool_enhance.md productionization pass
(2026-08-22).

Real, severe, empirically-verified finding: `chat_agent.py`'s real
dispatch had ZERO worktree-boundary validation (unlike the canonical
`make_read_only_handlers()` implementation, used by every
`run_agent_graph`-based agent and by `make_chat_handlers`). Proved
live: `read_file({"path": "/etc/hostname"})` through
`ChatAgent._execute_tool` genuinely returned a real host file's
content, completely outside the repo.

Despite 82 agents declaring `read_file` in `allowed_tools`
(tool_inventory.json), this is NOT 82 separate implementations — every
`run_agent_graph`-based agent and `make_chat_handlers` reach the SAME
single canonical `make_read_only_handlers()` factory; only
`chat_agent`'s own interactive dispatch was a genuinely separate
implementation, and the one with the real gap.

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.read_file import READ_FILE_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_read_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_read_file_tool_schema_requires_path() -> None:
    assert READ_FILE_TOOL["name"] == "read_file"
    assert READ_FILE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_only_tools_index_zero_is_still_read_file() -> None:
    """READ_ONLY_TOOLS[0] is indexed positionally elsewhere (e.g.
    RESEARCH_TOOLS) — must stay read_file at the same index."""
    assert READ_ONLY_TOOLS[0]["name"] == "read_file"


# ---------------------------------------------------------------------------
# The proven worktree-escape finding, verified closed on the real
# dispatch path that lacked protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_read_file_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "read_file_hardening_secret.txt"
    outside.write_text("host secret content")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("read_file", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "host secret content" not in result
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_read_file_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "read_file", {"path": "../../../../../../etc/hostname"}
    )
    assert "[POLICY DENIED]" in result


def test_canonical_read_only_handlers_still_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "read_file_hardening_secret2.txt"
    outside.write_text("host secret content")
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["read_file"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths, including the large-file folding safeguard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_read_file_reads_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("legit content")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("read_file", {"path": "hello.txt"})
    assert result == "legit content"


@pytest.mark.asyncio
async def test_chat_agent_read_file_missing_file_errors_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("read_file", {"path": "ghost.txt"})
    assert "[ERROR]" in result
    assert "not found" in result.lower()


def test_canonical_read_only_handlers_reads_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("legit content")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["read_file"]({"path": "hello.txt"})
    assert result == "legit content"


def test_make_chat_handlers_read_file_reads_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("legit content")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["read_file"]({"path": "hello.txt"})
    assert result == "legit content"


@pytest.mark.asyncio
async def test_chat_agent_read_file_folds_large_files_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parity finding: chat_agent.py's dispatch previously lacked the
    large-file folding/truncation safeguard the canonical implementation
    already had — now shares it via the same handler."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "file_fold_enabled", True)
    monkeypatch.setattr(settings, "file_fold_line_threshold", 5)

    big_file = tmp_path / "big.py"
    big_file.write_text("\n".join(f"def f{i}():\n    return {i}\n" for i in range(20)))

    agent = _agent(tmp_path)
    result = await agent._execute_tool("read_file", {"path": "big.py"})
    assert "[NOTE]" in result


def test_read_file_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_file") == 1
