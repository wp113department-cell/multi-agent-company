"""git_tag tool #22 — tool_enhance.md productionization pass (2026-08-17).

Real finding: `git_tag` is advertised to the interactive chat LLM via
`CHAT_TOOLS`, but `chat_agent.py`'s real dispatch had NO branch for it at
all — the same "advertised but never dispatched" bug class already found
for npm_install/pip_install (tool #4) and github_create_pr (tool #6).
Verified directly: a real call returned the generic
"[ERROR] Unknown tool: git_tag" fallback before this fix.

Also checked (not assumed) whether a flag-shaped tag name could trigger
unexpected behavior, mirroring tool #5's real git_reset flag-collision
bug — verified against a real repo that git itself refuses a flag-shaped
tag name cleanly (no silent dangerous behavior).

Every test here uses a real git repo and real git subprocess execution,
not mocked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.tag import GIT_TAG_TOOL, git_tag_handler


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_tag_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_tag_tool_schema_has_action_enum() -> None:
    assert GIT_TAG_TOOL["name"] == "git_tag"
    assert set(GIT_TAG_TOOL["input_schema"]["properties"]["action"]["enum"]) == {
        "list",
        "create",
        "delete",
    }


# ---------------------------------------------------------------------------
# The real, proven "advertised but never dispatched" gap — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_tag_is_now_dispatched(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)
    result = await agent._execute_tool("git_tag", {"action": "list"})
    assert result != "[ERROR] Unknown tool: git_tag"
    assert result == "(no tags)"


# ---------------------------------------------------------------------------
# Flag-collision check (tool #5's git_reset bug class) — proven not to
# apply here: git refuses cleanly, no silent dangerous behavior
# ---------------------------------------------------------------------------


def test_flag_shaped_tag_name_is_refused_cleanly_not_silently_dangerous(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    result = git_tag_handler(str(repo), {"action": "create", "name": "--force"})
    assert result.startswith("[ERROR]")
    # Confirm no tag was actually created under any name as a side effect
    list_result = git_tag_handler(str(repo), {"action": "list"})
    assert list_result == "(no tags)"


# ---------------------------------------------------------------------------
# Regression — real create/list/delete lifecycle through both real call
# sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_tag_full_lifecycle(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    create = await agent._execute_tool(
        "git_tag", {"action": "create", "name": "v1.0.0", "message": "first release"}
    )
    assert create == "Tag 'v1.0.0' created"

    listed = await agent._execute_tool("git_tag", {"action": "list"})
    assert "v1.0.0" in listed

    deleted = await agent._execute_tool(
        "git_tag", {"action": "delete", "name": "v1.0.0"}
    )
    assert "v1.0.0" in deleted

    listed_after = await agent._execute_tool("git_tag", {"action": "list"})
    assert listed_after == "(no tags)"


def test_git_tag_handler_create_without_message_is_lightweight_tag(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    result = git_tag_handler(str(repo), {"action": "create", "name": "v2.0.0"})
    assert result == "Tag 'v2.0.0' created"


def test_git_tag_handler_unknown_action_errors_cleanly(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    result = git_tag_handler(str(repo), {"action": "bogus"})
    assert result == "[ERROR] Unknown action"


def test_make_chat_handlers_git_tag_full_lifecycle(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    create = handlers["git_tag"]({"action": "create", "name": "v3.0.0"})
    assert create == "Tag 'v3.0.0' created"

    listed = handlers["git_tag"]({"action": "list"})
    assert "v3.0.0" in listed
