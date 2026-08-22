"""read_files tool #71 — tool_enhance.md productionization pass
(2026-08-22).

Real, severe, empirically-verified finding — worse than tool #65's
single-file `read_file` finding since this tool reads up to 20 files
per call: `chat_agent.py`'s real dispatch had ZERO worktree-boundary
validation on any path in the batch. Proved live:
`read_files({"paths": ["/etc/passwd", "/etc/hostname"]})` through
`ChatAgent._execute_tool` genuinely returned the real, full content of
both host files, completely outside the repo, in one call — a real
batch-exfiltration primitive. The canonical `make_read_only_handlers()`
implementation was NOT exploitable — already correctly validated every
path.

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
from app.tools.filesystem.read_files import READ_FILES_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_read_files_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_read_files_tool_schema_requires_paths() -> None:
    assert READ_FILES_TOOL["name"] == "read_files"
    assert READ_FILES_TOOL["input_schema"]["required"] == ["paths"]  # type: ignore[index]


def test_read_only_tools_index_six_is_still_read_files() -> None:
    assert READ_ONLY_TOOLS[6]["name"] == "read_files"


# ---------------------------------------------------------------------------
# The proven batch-exfiltration finding, verified closed on the real
# dispatch path that lacked protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_read_files_rejects_all_paths_outside_repo(
    tmp_path: Path,
) -> None:
    outside_a = tmp_path.parent / "read_files_hardening_secret_a.txt"
    outside_b = tmp_path.parent / "read_files_hardening_secret_b.txt"
    outside_a.write_text("secret A")
    outside_b.write_text("secret B")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "read_files", {"paths": [str(outside_a), str(outside_b)]}
        )
        assert "[POLICY DENIED]" in result
        assert "secret A" not in result
        assert "secret B" not in result
    finally:
        outside_a.unlink()
        outside_b.unlink()


@pytest.mark.asyncio
async def test_chat_agent_read_files_rejects_mixed_batch(tmp_path: Path) -> None:
    """A batch mixing a legitimate in-repo path with an outside-repo
    path must reject only the bad one, not fail the whole call."""
    (tmp_path / "legit.txt").write_text("legit content")
    outside = tmp_path.parent / "read_files_hardening_secret2.txt"
    outside.write_text("secret content")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "read_files", {"paths": ["legit.txt", str(outside)]}
        )
        assert "legit content" in result
        assert "secret content" not in result
        assert "[POLICY DENIED]" in result
    finally:
        outside.unlink()


def test_canonical_read_only_handlers_still_rejects_paths_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "read_files_hardening_secret3.txt"
    outside.write_text("secret content")
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["read_files"]({"paths": [str(outside)]})
        assert "[POLICY DENIED]" in result
        assert "secret content" not in result
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths, including the large-file folding safeguard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_read_files_reads_a_real_batch(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("content A")
    (tmp_path / "b.txt").write_text("content B")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("read_files", {"paths": ["a.txt", "b.txt"]})
    assert "content A" in result
    assert "content B" in result


def test_canonical_read_only_handlers_reads_a_real_batch(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("content A")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["read_files"]({"paths": ["a.txt"]})
    assert "content A" in result


def test_make_chat_handlers_read_files_reads_a_real_batch(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("content A")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["read_files"]({"paths": ["a.txt"]})
    assert "content A" in result


@pytest.mark.asyncio
async def test_chat_agent_read_files_folds_large_files_now(
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
    result = await agent._execute_tool("read_files", {"paths": ["big.py"]})
    assert "[NOTE]" in result


@pytest.mark.asyncio
async def test_chat_agent_read_files_offset_paging_still_works(
    tmp_path: Path,
) -> None:
    for i in range(25):
        (tmp_path / f"f{i}.txt").write_text(f"content {i}")
    paths = [f"f{i}.txt" for i in range(25)]
    agent = _agent(tmp_path)
    result = await agent._execute_tool("read_files", {"paths": paths})
    assert "[NOTICE]" in result
    assert "offset=20" in result


@pytest.mark.asyncio
async def test_chat_agent_read_files_missing_file_reported_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("read_files", {"paths": ["ghost.txt"]})
    assert "[ERROR]" in result


def test_read_files_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_files") == 1
