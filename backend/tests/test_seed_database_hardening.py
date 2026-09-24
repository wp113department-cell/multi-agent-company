"""seed_database tool #10 — tool_enhance.md productionization pass
(2026-08-16).

Real, empirically-verified findings (first diagnosed while auditing
run_migration, tool #8, closed here on this tool's own turn as planned):

1. chat_agent.py's real, reachable dispatch interpolated the
   LLM-controlled `script` value directly into a raw `shell=True` command
   string with zero validation. Proved directly before writing any fix:
   a crafted filename containing a shell metacharacter (which first
   requires a real file to exist at that literal path) actually executed
   an injected command when referenced via `script`.
2. A second, distinct vulnerability found while designing the fix for
   #1: `root / script` in Python's pathlib silently ignores `root`
   entirely when `script` is an absolute path — proved directly with
   script="/etc/hostname" resolving to that real file outside the repo,
   despite this tool's own schema documenting `script` as "relative to
   repo root."

Every test here proves the fix against the REAL dispatch method
(ChatAgent._execute_tool and the real make_chat_handlers() handler), not
a reimplementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_sd_hardening", repo_path=str(repo))
    return ChatAgent(session)


# ---------------------------------------------------------------------------
# Baseline + the two real exploits, proven to exist and proven closed
# ---------------------------------------------------------------------------


def test_shell_really_executes_a_semicolon_chained_command(tmp_path: Path) -> None:
    """Baseline proof — not this project's code, just confirming the real
    shell behavior the rest of this file's fix is built around."""
    marker = tmp_path / "PWNED_baseline"
    subprocess.run(
        f"echo hi; touch {marker}", shell=True, cwd=str(tmp_path), check=True
    )
    assert marker.exists()


def test_absolute_path_join_really_overrides_the_repo_root() -> None:
    """Baseline proof of the second real vulnerability's premise — not
    this project's code, just confirming real pathlib behavior: joining
    an absolute path onto a Path silently discards the left side."""
    root = Path("/some/repo/root")
    script = "/etc/hostname"
    assert str(root / script) == script


@pytest.mark.asyncio
async def test_seed_database_rejects_a_shell_injection_payload(
    tmp_path: Path,
) -> None:
    """The real exploit against the real, reachable chat_agent.py
    implementation: a crafted script filename containing a shell
    metacharacter must be rejected before ever reaching the shell."""
    repo = tmp_path
    marker = repo / "PWNED_seed_database"
    payload = f"seed.py; touch {marker}"

    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool("seed_database", {"script": payload})

    mock_confirm.assert_not_awaited()
    assert result.startswith("[ERROR]")
    assert not marker.exists()


@pytest.mark.asyncio
async def test_seed_database_rejects_other_shell_metacharacters(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    for payload in [
        "seed.py && echo pwned",
        "seed.py | echo pwned",
        "seed.py`echo pwned`",
        "seed.py$(echo pwned)",
        "seed.py > /tmp/x",
        "seed.py\npwned",
        "seed.py; rm -rf /",
    ]:
        with patch.object(
            agent, "_confirm", new=AsyncMock(return_value=True)
        ) as mock_confirm:
            result = await agent._execute_tool("seed_database", {"script": payload})
        mock_confirm.assert_not_awaited()
        assert result.startswith("[ERROR]"), f"payload not rejected: {payload!r}"


@pytest.mark.asyncio
async def test_seed_database_rejects_an_absolute_path_outside_the_repo(
    tmp_path: Path,
) -> None:
    """The real second exploit: an absolute path must not be allowed to
    override the intended repo root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = _agent(repo)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool("seed_database", {"script": "/etc/hostname"})

    mock_confirm.assert_not_awaited()
    assert result.startswith(("[ERROR]", "[POLICY DENIED]"))


@pytest.mark.asyncio
async def test_seed_database_rejects_a_dotdot_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "sibling_secret.py").write_text("# must not be reachable")
    agent = _agent(repo)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "seed_database", {"script": "../sibling_secret.py"}
        )

    mock_confirm.assert_not_awaited()
    assert result.startswith(("[ERROR]", "[POLICY DENIED]"))


def test_tools_py_handler_rejects_the_same_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sentry_environment", "development")
    handlers = make_chat_handlers(str(tmp_path))
    for payload in ["seed.py; touch /tmp/x", "/etc/hostname", "../outside.py"]:
        result = handlers["seed_database"]({"script": payload})
        assert result.startswith(
            ("[ERROR]", "[POLICY DENIED]")
        ), f"payload not rejected: {payload!r}"


# ---------------------------------------------------------------------------
# Regression — legitimate script paths must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_database_accepts_the_real_default_script_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path
    script_dir = repo / "backend" / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "seed.py").write_text("print('seeded')")

    agent = _agent(repo)
    with (
        patch.object(
            agent, "_confirm", new=AsyncMock(return_value=False)
        ) as mock_confirm,
    ):
        result = await agent._execute_tool("seed_database", {})

    mock_confirm.assert_awaited_once()
    assert result == "[CANCELLED] seed_database cancelled by user"


@pytest.mark.asyncio
async def test_seed_database_accepts_a_real_custom_relative_script(
    tmp_path: Path,
) -> None:
    repo = tmp_path
    (repo / "scripts").mkdir()
    (repo / "scripts" / "seed_test_data.py").write_text("print('seeded')")

    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=True)),
        patch(
            "app.agents.chat_agent._run_subprocess", return_value="seeded"
        ) as mock_run,
    ):
        result = await agent._execute_tool(
            "seed_database", {"script": "scripts/seed_test_data.py"}
        )

    mock_run.assert_called_once()
    assert result == "seeded"


@pytest.mark.asyncio
async def test_seed_database_still_errors_when_script_not_found(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "seed_database", {"script": "scripts/does_not_exist.py"}
    )
    assert result.startswith("[ERROR] Seed script not found")


def test_tools_py_handler_accepts_the_real_default_script_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sentry_environment", "development")
    script_dir = tmp_path / "backend" / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "seed.py").write_text("print('seeded')")

    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["seed_database"]({})
    assert result.startswith("[BLOCKED] seed_database requires interactive session")
