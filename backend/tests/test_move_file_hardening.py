"""move_file tool #52 — tool_enhance.md productionization pass
(2026-08-20).

Real, severe, empirically-verified finding (same class as tool #11's
copy_file bug — "never validated from_path at all... a real cross-repo
exfiltration primitive" — but worse here, since a MOVE also deletes
the original): the only real implementation validated `dest` but never
validated `source` at all. Proved live: an absolute path to a real
file completely outside the target repo was successfully relocated
into the repo via move_file — the original file was destroyed at its
source location. Same "advertised but never dispatched" reachability
class as tools #4/#6/#22/#25/#33/#44/#45/#46/#48/#50/#51 on top.

Every test here uses real files on disk and proves the fix against the
REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.move_file import MOVE_FILE_TOOL


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "existing.txt").write_text("repo content\n")
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_move_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_move_file_tool_schema_requires_fields() -> None:
    assert MOVE_FILE_TOOL["name"] == "move_file"
    assert MOVE_FILE_TOOL["input_schema"]["required"] == ["source", "dest"]  # type: ignore[index]


def test_move_file_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("move_file") == 1


# ---------------------------------------------------------------------------
# The proven exfiltration-and-delete finding — verified closed on both
# real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_move_file_rejects_outside_repo_source(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "secret.txt"
    victim.write_text("SENSITIVE HOST FILE CONTENT\n")

    agent = _agent(repo)
    result = await agent._execute_tool(
        "move_file", {"source": str(victim), "dest": "exfiltrated.txt"}
    )

    assert result.startswith("[POLICY DENIED]")
    assert victim.exists(), "the original file must survive untouched"
    assert victim.read_text() == "SENSITIVE HOST FILE CONTENT\n"
    assert not (repo / "exfiltrated.txt").exists()


def test_make_chat_handlers_move_file_rejects_outside_repo_source(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    outside = tmp_path / "outside2"
    outside.mkdir()
    victim = outside / "secret2.txt"
    victim.write_text("SENSITIVE 2\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["move_file"]({"source": str(victim), "dest": "exfil2.txt"})

    assert result.startswith("[POLICY DENIED]")
    assert victim.exists()
    assert not (repo / "exfil2.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_move_file_rejects_outside_repo_dest(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    outside_dest = tmp_path / "outside_dest.txt"
    agent = _agent(repo)

    result = await agent._execute_tool(
        "move_file", {"source": "existing.txt", "dest": str(outside_dest)}
    )

    assert result.startswith("[POLICY DENIED]")
    assert not outside_dest.exists()
    assert (repo / "existing.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_move_file_rejects_protected_source(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / ".env").write_text("SECRET=x\n")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "move_file", {"source": ".env", "dest": "moved.txt"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert (repo / ".env").exists()


# ---------------------------------------------------------------------------
# Regression — legitimate in-repo moves must keep working exactly as
# before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_move_file_real_move(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "move_file", {"source": "existing.txt", "dest": "renamed.txt"}
    )
    assert result == "Moved existing.txt → renamed.txt"
    assert not (repo / "existing.txt").exists()
    assert (repo / "renamed.txt").read_text() == "repo content\n"


def test_make_chat_handlers_move_file_real_move_across_subdirs(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["move_file"](
        {"source": "existing.txt", "dest": "subdir/moved.txt"}
    )
    assert result == "Moved existing.txt → subdir/moved.txt"
    assert (repo / "subdir" / "moved.txt").read_text() == "repo content\n"
