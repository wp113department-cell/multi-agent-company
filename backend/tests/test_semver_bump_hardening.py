"""semver_bump tool #25 — tool_enhance.md productionization pass
(2026-08-18).

Real findings:

1. "Advertised but never dispatched" (same class as tool #22's git_tag):
   semver_bump is in CHAT_TOOLS but chat_agent.py had no dispatch branch
   for it at all. Verified directly: a real call returned
   "[ERROR] Unknown tool: semver_bump" before this fix.
2. Real path-boundary-escape write (same class as tools #10/#11/...):
   the optional `file` field was joined with the repo root and both
   read AND rewritten with zero worktree-boundary validation. Proved
   directly: a real file outside the repo, containing a version-shaped
   string, was rewritten via `file` pointing outside the repo.

Every test here uses real files and real rewrites, and proves the fix
against the REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler), not a reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.semver_bump import SEMVER_BUMP_TOOL, semver_bump_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_semver_bump_hardening", repo_path=repo)
    return ChatAgent(session)


def test_semver_bump_tool_schema_has_part_enum() -> None:
    assert SEMVER_BUMP_TOOL["name"] == "semver_bump"
    assert set(SEMVER_BUMP_TOOL["input_schema"]["properties"]["part"]["enum"]) == {
        "patch",
        "minor",
        "major",
    }


# ---------------------------------------------------------------------------
# The real, proven "advertised but never dispatched" gap — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_semver_bump_is_now_dispatched(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text('version = "1.0.0"')
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("semver_bump", {"part": "patch"})
    assert result != "[ERROR] Unknown tool: semver_bump"
    assert result == "Bumped version to 1.0.1 in VERSION"


# ---------------------------------------------------------------------------
# The real, proven path-escape write — verified closed
# ---------------------------------------------------------------------------


def test_handler_rejects_file_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_VERSION"
    outside.write_text('version = "1.2.3"')

    result = semver_bump_handler(
        repo, str(repo), {"part": "major", "file": str(outside)}
    )
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == 'version = "1.2.3"'


def test_handler_rejects_dotdot_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sibling = tmp_path / "sibling_VERSION"
    sibling.write_text('version = "1.2.3"')

    result = semver_bump_handler(
        repo, str(repo), {"part": "major", "file": "../sibling_VERSION"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert sibling.read_text() == 'version = "1.2.3"'


@pytest.mark.asyncio
async def test_chat_agent_semver_bump_rejects_file_outside_worktree(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"td_semver_outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    victim = outside / "VERSION"
    victim.write_text('version = "1.2.3"')
    agent = _agent(str(tmp_path))

    result = await agent._execute_tool(
        "semver_bump", {"part": "patch", "file": str(victim)}
    )
    assert result.startswith("[POLICY DENIED]")
    assert victim.read_text() == 'version = "1.2.3"'


# ---------------------------------------------------------------------------
# Regression — legitimate version bumps must keep working exactly as
# before, across every part and every candidate file
# ---------------------------------------------------------------------------


def test_handler_bumps_patch(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text('version = "1.2.3"')
    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "patch"})
    assert result == "Bumped version to 1.2.4 in VERSION"


def test_handler_bumps_minor_resets_patch(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text('version = "1.2.3"')
    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "minor"})
    assert result == "Bumped version to 1.3.0 in VERSION"


def test_handler_bumps_major_resets_minor_and_patch(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text('version = "1.2.3"')
    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "major"})
    assert result == "Bumped version to 2.0.0 in VERSION"


def test_handler_finds_pyproject_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "patch"})
    assert result == "Bumped version to 0.1.1 in pyproject.toml"
    assert 'version = "0.1.1"' in (tmp_path / "pyproject.toml").read_text()


def test_handler_accepts_a_real_relative_in_repo_file(tmp_path: Path) -> None:
    (tmp_path / "custom_VERSION").write_text('version = "1.0.0"')
    result = semver_bump_handler(
        tmp_path, str(tmp_path), {"part": "patch", "file": "custom_VERSION"}
    )
    assert result == "Bumped version to 1.0.1 in custom_VERSION"


def test_handler_errors_when_no_version_file_found(tmp_path: Path) -> None:
    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "patch"})
    assert result.startswith("[ERROR] No version file found")


def test_make_chat_handlers_semver_bump_still_works(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text('version = "1.0.0"')
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["semver_bump"]({"part": "major"})
    assert result == "Bumped version to 2.0.0 in VERSION"
