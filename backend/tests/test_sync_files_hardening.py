"""sync_files tool #64 — tool_enhance.md productionization pass
(2026-08-22).

Real, severe, empirically-verified finding: `chat_agent.py`'s real
dispatch had ZERO worktree-boundary validation on either `source` or
any `paths` entry (`tools.py`'s own implementation already had it via
`check_path_in_worktree()`). Proved live, combined in one call: `source
="/etc/hostname"` (a real file outside the repo) with `paths=
["exfiltrated.txt", "/tmp/PWNED.txt"]` genuinely read the host file and
wrote its content both INTO the repo (exfiltration) and to an arbitrary
path OUTSIDE the repo (arbitrary write). This tool appears to have been
missed by tool #11's cross-cutting worktree-boundary sweep.

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.sync_files import SYNC_FILES_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_sync_files_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_sync_files_tool_schema_requires_source_and_paths() -> None:
    assert SYNC_FILES_TOOL["name"] == "sync_files"
    assert SYNC_FILES_TOOL["input_schema"]["required"] == ["source", "paths"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# The proven combined exfiltration + arbitrary-write finding, verified
# closed on the real dispatch path that lacked protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_sync_files_rejects_source_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "sync_files_hardening_secret.txt"
    outside.write_text("host secret content")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "sync_files", {"source": str(outside), "paths": ["exfiltrated.txt"]}
        )
        assert "[POLICY DENIED]" in result or "[ERROR]" in result
        assert not (
            tmp_path / "exfiltrated.txt"
        ).exists(), "must not read+write an outside-repo source into the repo"
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_sync_files_rejects_target_outside_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.txt").write_text("legit content")
    outside_target = tmp_path.parent / "sync_files_hardening_outside_write.txt"
    if outside_target.exists():
        outside_target.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "sync_files",
            {"source": "source.txt", "paths": [str(outside_target)]},
        )
        assert "[POLICY DENIED]" in result
        assert (
            not outside_target.exists()
        ), "must not write a target file outside the repo"
    finally:
        if outside_target.exists():
            outside_target.unlink()


@pytest.mark.asyncio
async def test_chat_agent_sync_files_combined_exploit_fully_blocked(
    tmp_path: Path,
) -> None:
    """The exact live-proven exploit shape: an outside-repo source read
    combined with one in-repo target (exfiltration) and one outside-repo
    target (arbitrary write) in a single call."""
    outside_target = tmp_path.parent / "sync_files_hardening_combined_pwn.txt"
    if outside_target.exists():
        outside_target.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "sync_files",
            {
                "source": "/etc/hostname",
                "paths": ["exfiltrated2.txt", str(outside_target)],
            },
        )
        assert "[POLICY DENIED]" in result
        assert not (tmp_path / "exfiltrated2.txt").exists()
        assert not outside_target.exists()
    finally:
        if outside_target.exists():
            outside_target.unlink()


def test_make_chat_handlers_sync_files_rejects_source_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "sync_files_hardening_secret2.txt"
    outside.write_text("host secret content")
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["sync_files"](
            {"source": str(outside), "paths": ["exfiltrated3.txt"]}
        )
        assert "[POLICY DENIED]" in result
        assert not (tmp_path / "exfiltrated3.txt").exists()
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_sync_files_creates_and_updates_real_targets(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text("hello")
    agent = _agent(tmp_path)

    result = await agent._execute_tool(
        "sync_files", {"source": "a.txt", "paths": ["b.txt", "sub/c.txt"]}
    )
    assert "created" in result
    assert (tmp_path / "b.txt").read_text() == "hello"
    assert (tmp_path / "sub" / "c.txt").read_text() == "hello"

    result2 = await agent._execute_tool(
        "sync_files", {"source": "a.txt", "paths": ["b.txt"]}
    )
    assert "unchanged" in result2

    (tmp_path / "a.txt").write_text("updated")
    result3 = await agent._execute_tool(
        "sync_files", {"source": "a.txt", "paths": ["b.txt"]}
    )
    assert "updated" in result3
    assert (tmp_path / "b.txt").read_text() == "updated"


def test_make_chat_handlers_sync_files_creates_real_target(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["sync_files"]({"source": "a.txt", "paths": ["b.txt"]})
    assert "created" in result
    assert (tmp_path / "b.txt").read_text() == "hello"


@pytest.mark.asyncio
async def test_chat_agent_sync_files_missing_source_errors_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "sync_files", {"source": "nope.txt", "paths": ["x.txt"]}
    )
    assert "[ERROR]" in result


def test_sync_files_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("sync_files") == 1
