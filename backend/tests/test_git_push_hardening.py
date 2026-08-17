"""git_push tool #4 — tool_enhance.md productionization pass (2026-08-16).

Real findings, each with a direct test here:
1. chat_agent.py's git_push force-push didn't get the "extra confirmation"
   its own tool description promises — force and normal pushes got the
   identical confirmation dialog. Fixed with a distinct, stronger warning,
   naming the real risk explicitly for a configured protected branch.
2. A much bigger, systemic finding while auditing this: `session` is
   never non-None for any real caller of app.agents.tools.
   make_chat_handlers() anywhere in the repo (confirmed by repository-wide
   grep — every real one-shot agent factory calls it with only
   repo_path). 8 handlers there (git_push, bash-dangerous, docker_compose,
   undo_changes, run_migration, seed_database, npm_install, pip_install)
   attempted a session.request_confirmation()-based confirmation flow that
   could never execute in production. Removed as dead code — see
   docs/tool_productionization/git_push.md for the full audit.
3. docker_compose('up') was the one exception: docker_agent, a real
   registered one-shot agent, genuinely has docker_compose in its
   allowed_tools, so its 'up' action was a live, permanently-broken dead
   end (every other docker_compose action still worked). Fixed with a
   fail-closed, config-driven gate matching create_pr_require_approval's
   precedent (tool #2's second pass) — and the interactive chat agent's
   own real docker_compose('up') dispatch, which previously had NO
   confirmation gate at all, now has a genuine one.
4. npm_install/npm_run/pip_install are advertised to the interactive chat
   LLM via CHAT_TOOLS/AGENT_CONTRACT["allowed_tools"], but chat_agent.py's
   _execute_tool had no dispatch branch for any of them at all — every
   real call from the interactive chat agent fell through to a generic
   "[ERROR] Unknown tool" response. Wired real dispatch for all three.

Tests call ChatAgent._execute_tool directly (not the full interrupt/
pause/resume graph machinery, already proven generically for git_push and
create_pr in test_phase52_chat_graph_interrupt.py) — these tests are
about WHAT gets confirmed/dispatched and how, not the pause/resume
mechanism itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.config import get_settings
from app.models.chat import ChatSession


def _confirm_description(mock_confirm: AsyncMock) -> str:
    call = mock_confirm.await_args
    assert call is not None
    return str(call.kwargs.get("description") or call.args[0])


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_gp_hardening", repo_path=str(repo))
    return ChatAgent(session)


# ---------------------------------------------------------------------------
# 1. chat_agent.py git_push — force push to a protected branch gets a
# distinct, stronger confirmation, matching the tool's own promise.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_push_gets_the_generic_confirmation(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=False)) as mock_confirm,
        patch("app.agents.chat_agent._git", return_value="pushed"),
    ):
        await agent._execute_tool("git_push", {"branch": "feature-x"})

    mock_confirm.assert_awaited_once()
    description = _confirm_description(mock_confirm)
    assert description == "Push commits to remote repository"


@pytest.mark.asyncio
async def test_force_push_to_a_feature_branch_gets_a_force_warning(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=False)) as mock_confirm,
        patch("app.agents.chat_agent._git", return_value="pushed"),
    ):
        await agent._execute_tool(
            "git_push", {"branch": "feature-x", "force": True}
        )

    mock_confirm.assert_awaited_once()
    description = _confirm_description(mock_confirm)
    assert "FORCE PUSH" in description
    assert "protected" not in description.lower()


@pytest.mark.asyncio
async def test_force_push_to_a_protected_branch_gets_the_strongest_warning(
    tmp_path: Path,
) -> None:
    """The real regression this closes: previously force and normal
    pushes got the IDENTICAL confirmation, contradicting the tool's own
    schema description ("Force push... requires extra confirmation")."""
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=False)) as mock_confirm,
        patch("app.agents.chat_agent._git", return_value="pushed"),
    ):
        await agent._execute_tool("git_push", {"branch": "main", "force": True})

    mock_confirm.assert_awaited_once()
    description = _confirm_description(mock_confirm)
    assert "FORCE PUSH" in description
    assert "protected branch 'main'" in description
    assert "overwrite remote history" in description.lower()


@pytest.mark.asyncio
async def test_force_push_with_no_explicit_branch_resolves_current_branch(
    tmp_path: Path,
) -> None:
    """branch='' means git pushes whatever is currently checked out — the
    protected-branch check must resolve that real branch, not skip the
    check just because the caller didn't name one explicitly."""
    repo = _git_repo(tmp_path)  # current branch is 'main' after _git_repo()
    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=False)
    ) as mock_confirm:
        await agent._execute_tool("git_push", {"force": True})

    mock_confirm.assert_awaited_once()
    description = _confirm_description(mock_confirm)
    assert "protected branch 'main'" in description


@pytest.mark.asyncio
async def test_git_push_protected_branches_is_config_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    monkeypatch.setattr(get_settings(), "git_push_protected_branches", ["release"])
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=False)) as mock_confirm,
        patch("app.agents.chat_agent._git", return_value="pushed"),
    ):
        # 'main' is no longer configured as protected — falls back to the
        # generic force-push warning, not the protected-branch one.
        await agent._execute_tool("git_push", {"branch": "main", "force": True})

    description = _confirm_description(mock_confirm)
    assert "FORCE PUSH" in description
    assert "protected" not in description.lower()


# ---------------------------------------------------------------------------
# 2. tools.py's dead session-gated handlers — now a clean, unconditional
# refusal, no dead async plumbing, regardless of what `session` is.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("git_push", {}),
        ("undo_changes", {"path": "a.txt"}),
        ("run_migration", {}),
        ("seed_database", {}),
        ("npm_install", {}),
        ("pip_install", {"package": "requests"}),
    ],
)
def test_dead_session_gated_handlers_always_refuse(
    tmp_path: Path, tool_name: str, payload: dict[str, object]
) -> None:
    from unittest.mock import AsyncMock as _AsyncMock
    from unittest.mock import MagicMock

    repo = _git_repo(tmp_path)
    real_session = MagicMock()
    real_session.request_confirmation = _AsyncMock(return_value=True)

    handlers_no_session = make_chat_handlers(str(repo))
    handlers_with_session = make_chat_handlers(str(repo), session=real_session)

    out_no_session = handlers_no_session[tool_name](payload)
    out_with_session = handlers_with_session[tool_name](payload)

    assert "[BLOCKED]" in out_no_session
    assert "[BLOCKED]" in out_with_session
    real_session.request_confirmation.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. docker_compose('up') — real, live gap for docker_agent (unlike the
# tools above, this one had a genuine reachable caller).
# ---------------------------------------------------------------------------


def test_docker_compose_up_fails_closed_by_default(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))
    with patch("app.agents.tools.subprocess.run") as mock_run:
        result = handlers["docker_compose"]({"action": "up"})
    assert result.startswith("[POLICY DENIED]")
    mock_run.assert_not_called()


def test_docker_compose_other_actions_are_unaffected(tmp_path: Path) -> None:
    """Only 'up' (container creation) is gated — 'ps'/'logs'/etc. were
    never session-gated and must keep working exactly as before."""
    repo = _git_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    class _FakeResult:
        stdout = "no containers"
        stderr = ""

    with patch(
        "app.agents.tools.subprocess.run", return_value=_FakeResult()
    ) as mock_run:
        result = handlers["docker_compose"]({"action": "ps"})
    assert "no containers" in result
    mock_run.assert_called_once()


def test_docker_compose_up_opt_out_flag_allows_it_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.setattr(get_settings(), "docker_compose_up_require_approval", False)
    handlers = make_chat_handlers(str(repo))

    class _FakeResult:
        stdout = "Started"
        stderr = ""

    with patch(
        "app.agents.tools.subprocess.run", return_value=_FakeResult()
    ) as mock_run:
        result = handlers["docker_compose"]({"action": "up"})
    assert "Started" in result
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_up_now_requires_confirmation(
    tmp_path: Path,
) -> None:
    """Real gap found: chat_agent.py's OWN docker_compose dispatch had NO
    confirmation for 'up' at all before this fix, despite tools.py's
    (unreachable) sibling correctly identifying it as needing one."""
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=False)) as mock_confirm,
        patch("app.agents.chat_agent._run_subprocess", return_value="ok"),
    ):
        result = await agent._execute_tool("docker_compose", {"action": "up"})

    mock_confirm.assert_awaited_once()
    assert "[DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_down_still_has_no_confirmation(
    tmp_path: Path,
) -> None:
    """Regression proof — only 'up' should ever pause; 'down'/'ps'/etc.
    must keep running immediately, matching their pre-existing behavior."""
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock()) as mock_confirm,
        patch("app.agents.chat_agent._run_subprocess", return_value="stopped"),
    ):
        result = await agent._execute_tool("docker_compose", {"action": "down"})

    mock_confirm.assert_not_awaited()
    assert "stopped" in result


# ---------------------------------------------------------------------------
# 4. npm_install / npm_run / pip_install — real bug: advertised to the
# interactive chat LLM but had no dispatch at all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_npm_install_was_previously_unknown_tool_now_dispatches(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=False)
    ) as mock_confirm:
        result = await agent._execute_tool("npm_install", {"directory": "."})

    mock_confirm.assert_awaited_once()
    assert result != "[ERROR] Unknown tool: npm_install"
    assert "[DENIED]" in result


@pytest.mark.asyncio
async def test_npm_install_runs_for_real_when_approved(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)

    class _FakeResult:
        stdout = "added 1 package"
        stderr = ""

    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=True)),
        patch("subprocess.run", return_value=_FakeResult()) as mock_run,
    ):
        result = await agent._execute_tool("npm_install", {"directory": "."})

    mock_run.assert_called_once()
    assert "added 1 package" in result


@pytest.mark.asyncio
async def test_pip_install_was_previously_unknown_tool_now_dispatches(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=False)
    ) as mock_confirm:
        result = await agent._execute_tool("pip_install", {"package": "requests"})

    mock_confirm.assert_awaited_once()
    assert result != "[ERROR] Unknown tool: pip_install"
    assert "[DENIED]" in result


@pytest.mark.asyncio
async def test_npm_run_was_previously_unknown_tool_now_dispatches_without_confirmation(
    tmp_path: Path,
) -> None:
    """npm_run (running an existing package.json script) is lower-risk
    than installing new dependencies — matches tools.py's own npm_run_h
    precedent of no confirmation gate."""
    repo = _git_repo(tmp_path)
    agent = _agent(repo)

    class _FakeResult:
        stdout = "build complete"
        stderr = ""

    with (
        patch.object(agent, "_confirm", new=AsyncMock()) as mock_confirm,
        patch("subprocess.run", return_value=_FakeResult()),
    ):
        result = await agent._execute_tool("npm_run", {"script": "build"})

    mock_confirm.assert_not_awaited()
    assert result != "[ERROR] Unknown tool: npm_run"
    assert "build complete" in result


def test_npm_install_pip_install_npm_run_are_advertised_to_the_chat_llm() -> None:
    """Confirms the real premise of this whole finding: these 3 tools ARE
    in CHAT_TOOLS (and therefore chat_agent's own allowed_tools), so a
    missing dispatch really was a live, reachable bug — not dead code."""
    from app.agents.chat_agent import AGENT_CONTRACT

    for name in ("npm_install", "npm_run", "pip_install"):
        assert name in AGENT_CONTRACT["allowed_tools"]
