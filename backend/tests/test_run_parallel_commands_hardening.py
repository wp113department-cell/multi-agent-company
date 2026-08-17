"""run_parallel_commands tool #9 — tool_enhance.md productionization pass
(2026-08-16).

Real, empirically-verified finding: the `cwd` field (per-command in
run_parallel_commands, and the single `cwd` field in the generic `bash`
tool — both share the identical vulnerability, fixed together per
explicit user direction since bash's copy meant tool #1's earlier GREEN
FLAG was issued before this was found) is fully LLM-controlled and was
passed straight through to the real sandboxed execution primitive
(app.policy.sandbox.run_sandboxed) with NO validation that it stays
inside the caller's own repo. run_sandboxed() mounts whatever `cwd` it
receives read-write as the container's /workspace.

Proved directly before writing any fix (not assumed): a real directory
outside any intended worktree was mounted into the sandbox and a file
inside it was read back through the container — confirming an LLM (or a
prompt-injection attack) could point `cwd` at an arbitrary host
directory and gain real read/write access to it, completely bypassing
the "stay inside your own repo worktree" assumption the whole sandbox
design rests on.

Fixed by validating every `cwd` through `check_path_in_worktree` (the
same, already-established mechanism this codebase already uses for
write_file/edit_file's own path arguments) before it ever reaches the
sandboxed execution primitive — in chat_agent.py's real `bash` and
`run_parallel_commands` dispatches, and in the (currently unreachable,
kept for defense-in-depth) tools.py `run_parallel_commands_h` handler.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_rpc_hardening", repo_path=str(repo))
    return ChatAgent(session)


# ---------------------------------------------------------------------------
# The real exploit — proven closed against the real Docker sandbox, no
# mocking of the execution mechanism itself.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bash_tool_rejects_a_cwd_outside_the_worktree(tmp_path: Path) -> None:
    """The exact real exploit against the generic bash tool: a cwd
    pointed at an unrelated directory must never reach the sandbox."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_the_worktree"
    outside.mkdir()
    (outside / "secret.txt").write_text("must not be reachable")

    agent = _agent(repo)
    result = await agent._execute_tool(
        "bash", {"command": "cat secret.txt", "cwd": str(outside)}
    )

    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_run_parallel_commands_rejects_a_cwd_outside_the_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_the_worktree"
    outside.mkdir()
    (outside / "secret.txt").write_text("must not be reachable")

    agent = _agent(repo)
    result = await agent._execute_tool(
        "run_parallel_commands",
        {
            "commands": [
                {"command": "echo fine"},
                {"command": "cat secret.txt", "cwd": str(outside)},
            ]
        },
    )

    assert result.startswith("[POLICY DENIED]")


def test_tools_py_run_parallel_commands_rejects_a_cwd_outside_the_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_the_worktree"
    outside.mkdir()
    (outside / "secret.txt").write_text("must not be reachable")

    handlers = make_chat_handlers(str(repo))
    result = handlers["run_parallel_commands"](
        {
            "commands": [
                {"command": "echo fine"},
                {"command": "cat secret.txt", "cwd": str(outside)},
            ]
        }
    )

    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_cwd_via_dotdot_traversal_is_also_rejected(tmp_path: Path) -> None:
    """A relative cwd using ../ to escape the worktree must be caught the
    same way an absolute outside path is — check_path_in_worktree
    resolves via realpath, not a naive string prefix check."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "sibling_secret.txt").write_text("must not be reachable")

    agent = _agent(repo)
    result = await agent._execute_tool("bash", {"command": "ls", "cwd": "../"})

    assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# Regression — legitimate cwd usage (inside the worktree, including a real
# subdirectory) must keep working exactly as before.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bash_tool_accepts_a_cwd_inside_the_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subdir = repo / "apps" / "web"
    subdir.mkdir(parents=True)
    (subdir / "marker.txt").write_text("hello")

    agent = _agent(repo)
    with patch.object(agent, "_confirm", new=AsyncMock()) as mock_confirm:
        result = await agent._execute_tool(
            "bash", {"command": "cat marker.txt", "cwd": str(subdir)}
        )

    mock_confirm.assert_not_awaited()  # "cat" isn't a dangerous command
    assert "hello" in result


@pytest.mark.asyncio
async def test_bash_tool_no_cwd_still_defaults_to_the_repo_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "marker.txt").write_text("root marker")

    agent = _agent(repo)
    result = await agent._execute_tool("bash", {"command": "cat marker.txt"})
    assert "root marker" in result


@pytest.mark.asyncio
async def test_run_parallel_commands_accepts_cwds_inside_the_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    backend = repo / "backend"
    frontend = repo / "apps" / "web"
    backend.mkdir(parents=True)
    frontend.mkdir(parents=True)
    (backend / "b.txt").write_text("backend-marker")
    (frontend / "f.txt").write_text("frontend-marker")

    agent = _agent(repo)
    result = await agent._execute_tool(
        "run_parallel_commands",
        {
            "commands": [
                {"command": "cat b.txt", "cwd": str(backend)},
                {"command": "cat f.txt", "cwd": str(frontend)},
            ]
        },
    )

    assert "backend-marker" in result
    assert "frontend-marker" in result


def test_tools_py_run_parallel_commands_accepts_cwds_inside_the_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    subdir = repo / "backend"
    subdir.mkdir(parents=True)
    (subdir / "marker.txt").write_text("subdir marker")

    handlers = make_chat_handlers(str(repo))
    result = handlers["run_parallel_commands"](
        {"commands": [{"command": "cat marker.txt", "cwd": str(subdir)}]}
    )

    assert "subdir marker" in result
