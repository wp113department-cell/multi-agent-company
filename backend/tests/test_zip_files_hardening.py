"""zip_files tool #209 — tool_enhance.md productionization pass
(2026-09-16).

Three real, empirically-verified findings on the one real
implementation (`zip_files_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn) — the write-side finding is a severe "arbitrary file write with
real, attacker-chosen content" primitive, the same severity tier as
sibling tool #206's (`unzip_files`) `dest` finding.

1. `output` had zero worktree-boundary validation — a genuine
   content-exfiltration primitive. Proved live: a real repo file's
   content was zipped and written to an arbitrary absolute path
   completely outside the worktree, confirmed by reading the
   exfiltrated archive back and finding the real secret string inside.
2. `source` had zero worktree-boundary validation.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204/#206/#207/#208).

All closed via a shared `zip_files_handler()` using
`check_path_in_worktree()` on both `source` and `output`.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.zip_files import ZIP_FILES_TOOL, zip_files_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_zip_files_hardening", repo_path=repo)
    return ChatAgent(session)


def test_zip_files_tool_schema() -> None:
    assert ZIP_FILES_TOOL["name"] == "zip_files"
    assert ZIP_FILES_TOOL["input_schema"]["required"] == ["source"]  # type: ignore[index]


def test_zip_files_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("zip_files") == 1


# ---------------------------------------------------------------------------
# Finding #1 — content-exfiltration via unvalidated absolute `output`
# ---------------------------------------------------------------------------


def test_handler_blocks_content_exfiltration_via_absolute_output(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "secret_config.py").write_text("API_KEY=sk-real-secret-12345")
    outside_zip = tmp_path / "outside" / "exfil.zip"

    result = zip_files_handler(
        repo, str(repo), {"source": "secret_config.py", "output": str(outside_zip)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside_zip.exists()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_blocks_content_exfiltration(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "secret_config.py").write_text("API_KEY=sk-real-secret-12345")
    outside_zip = tmp_path / "outside" / "exfil.zip"

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "zip_files", {"source": "secret_config.py", "output": str(outside_zip)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside_zip.exists()


def test_make_chat_handlers_blocks_content_exfiltration(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "secret_config.py").write_text("API_KEY=sk-real-secret-12345")
    outside_zip = tmp_path / "outside" / "exfil.zip"

    handlers = make_chat_handlers(str(repo))
    result = handlers["zip_files"](
        {"source": "secret_config.py", "output": str(outside_zip)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside_zip.exists()


def test_handler_allows_a_real_absolute_output_inside_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("hello")
    inside_absolute_output = str(repo / "out.zip")

    result = zip_files_handler(
        repo, str(repo), {"source": "a.txt", "output": inside_absolute_output}
    )
    assert "Zipped" in result
    assert (repo / "out.zip").exists()


# ---------------------------------------------------------------------------
# Finding #2 — worktree-escape on source
# ---------------------------------------------------------------------------


def test_handler_blocks_source_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_file = tmp_path / "host_secret.txt"
    outside_file.write_text("host secret content")

    result = zip_files_handler(repo, str(repo), {"source": str(outside_file)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("zip_files", {"source": "a.txt"})
    assert "Unknown tool" not in result
    assert "Zipped" in result
    assert (tmp_path / "a.txt.zip").exists()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_zips_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    result = zip_files_handler(tmp_path, str(tmp_path), {"source": "a.txt"})
    assert "Zipped" in result
    zpath = tmp_path / "a.txt.zip"
    assert zpath.exists()
    with zipfile.ZipFile(zpath) as zf:
        assert zf.read("a.txt") == b"hello"


def test_handler_zips_a_real_directory(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "file.txt").write_text("content")
    result = zip_files_handler(
        tmp_path, str(tmp_path), {"source": "mydir", "output": "out.zip"}
    )
    assert "Zipped" in result
    with zipfile.ZipFile(tmp_path / "out.zip") as zf:
        assert "mydir/file.txt" in zf.namelist()


def test_handler_errors_cleanly_on_missing_source(tmp_path: Path) -> None:
    result = zip_files_handler(tmp_path, str(tmp_path), {"source": "ghost.txt"})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_zips_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("zip_files", {"source": "a.txt"})
    assert "Zipped" in result
    with zipfile.ZipFile(tmp_path / "a.txt.zip") as zf:
        assert zf.read("a.txt") == b"hello"
