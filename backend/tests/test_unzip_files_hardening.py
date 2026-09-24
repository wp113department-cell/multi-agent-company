"""unzip_files tool #206 — tool_enhance.md productionization pass
(2026-09-16).

Three real, empirically-verified findings — a severe "arbitrary file
write" class primitive, on the one real implementation
(`unzip_files_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn).

1. `dest` resolution was a tautological ternary
   (`root / dest if not (root / dest).is_absolute() else Path(dest)`)
   that ALWAYS evaluated to `Path(dest)`, discarding `root` in every
   real call — both a functional bug (relative dest resolves against
   the process cwd, not the repo root) and an arbitrary-directory-
   write primitive (absolute dest extracts anywhere on the host).
   Proved live both ways.
2. `archive` had zero worktree-boundary validation.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204).

Classic "zip slip" via crafted archive entry names was investigated
and empirically REFUTED on this project's real Python 3.12.3
`zipfile.extractall()` — already sanitizes traversal/absolute entry
names.

All three closed via a shared `unzip_files_handler()` using
`check_path_in_worktree()` on both `archive` and the resolved `dest`,
with `dest` now correctly resolved against `root` when relative.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.unzip_files import UNZIP_FILES_TOOL, unzip_files_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_unzip_files_hardening", repo_path=repo)
    return ChatAgent(session)


def _make_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)


def test_unzip_files_tool_schema() -> None:
    assert UNZIP_FILES_TOOL["name"] == "unzip_files"
    assert UNZIP_FILES_TOOL["input_schema"]["required"] == ["archive"]  # type: ignore[index]


def test_unzip_files_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("unzip_files") == 1


# ---------------------------------------------------------------------------
# Finding #1 — dest resolution bug / arbitrary-directory-write escape
# ---------------------------------------------------------------------------


def test_handler_resolves_relative_dest_against_root_not_cwd(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_zip(repo / "a.zip", {"file.txt": "hello"})

    result = unzip_files_handler(repo, str(repo), {"archive": "a.zip", "dest": "out"})
    assert "Extracted" in result
    assert (repo / "out" / "file.txt").exists()


def test_handler_blocks_absolute_dest_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    _make_zip(repo / "a.zip", {"payload.txt": "malicious"})

    result = unzip_files_handler(
        repo, str(repo), {"archive": "a.zip", "dest": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert not (outside / "payload.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_blocks_absolute_dest_outside_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    _make_zip(repo / "a.zip", {"payload.txt": "malicious"})

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "unzip_files", {"archive": "a.zip", "dest": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert not (outside / "payload.txt").exists()


def test_make_chat_handlers_blocks_absolute_dest_outside_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    _make_zip(repo / "a.zip", {"payload.txt": "malicious"})

    handlers = make_chat_handlers(str(repo))
    result = handlers["unzip_files"]({"archive": "a.zip", "dest": str(outside)})
    assert "[POLICY DENIED]" in result
    assert not (outside / "payload.txt").exists()


def test_handler_allows_a_real_absolute_dest_inside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_zip(repo / "a.zip", {"file.txt": "hello"})
    inside_absolute = str(repo / "out")

    result = unzip_files_handler(
        repo, str(repo), {"archive": "a.zip", "dest": inside_absolute}
    )
    assert "Extracted" in result
    assert (repo / "out" / "file.txt").exists()


# ---------------------------------------------------------------------------
# Finding #2 — worktree-escape on archive (source)
# ---------------------------------------------------------------------------


def test_handler_blocks_archive_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_zip = tmp_path / "secret.zip"
    _make_zip(outside_zip, {"secret.txt": "classified"})

    result = unzip_files_handler(repo, str(repo), {"archive": str(outside_zip)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    _make_zip(tmp_path / "a.zip", {"file.txt": "hi"})
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "unzip_files", {"archive": "a.zip", "dest": "out"}
    )
    assert "Unknown tool" not in result
    assert "Extracted" in result
    assert (tmp_path / "out" / "file.txt").exists()


# ---------------------------------------------------------------------------
# Investigated and refuted — zip slip via crafted entry names
# ---------------------------------------------------------------------------


def test_zip_slip_via_traversal_entry_is_refuted(tmp_path: Path) -> None:
    """Not a real vulnerability on this project's real Python runtime —
    zipfile.extractall() already sanitizes traversal entries. Kept as
    a regression guard, not a security fix."""
    repo = tmp_path / "repo"
    repo.mkdir()
    zpath = repo / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../../../../tmp/PWNED_ZIP_SLIP.txt", "pwned")

    result = unzip_files_handler(
        repo, str(repo), {"archive": "evil.zip", "dest": "out"}
    )
    assert "Extracted" in result
    assert not Path("/tmp/PWNED_ZIP_SLIP.txt").exists()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_extracts_a_real_archive(tmp_path: Path) -> None:
    _make_zip(tmp_path / "a.zip", {"f1.txt": "one", "sub/f2.txt": "two"})
    result = unzip_files_handler(tmp_path, str(tmp_path), {"archive": "a.zip"})
    assert "Extracted" in result
    assert (tmp_path / "f1.txt").exists()
    assert (tmp_path / "sub" / "f2.txt").exists()


def test_handler_errors_cleanly_on_missing_archive(tmp_path: Path) -> None:
    result = unzip_files_handler(tmp_path, str(tmp_path), {"archive": "ghost.zip"})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_extracts_a_real_archive(tmp_path: Path) -> None:
    _make_zip(tmp_path / "a.zip", {"f1.txt": "one"})
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("unzip_files", {"archive": "a.zip"})
    assert "Extracted" in result
    assert (tmp_path / "f1.txt").exists()
