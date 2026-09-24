"""run_migration tool #8 — tool_enhance.md productionization pass
(2026-08-16).

Real, empirically-verified finding: chat_agent.py's real, reachable
run_migration dispatch interpolated LLM-controlled `direction`/`revision`
values directly into a raw `shell=True` command string with zero
validation. Proved directly before writing any fix (not assumed): a
harmless payload (`revision="head; touch /tmp/PWNED..."`) actually
executed the injected command against a real shell. This bypassed the
confirmation dialog's entire purpose — a human reviewing "alembic upgrade
<revision>" has no reasonable way to notice an injection payload hidden
inside what looks like a revision identifier.

Fixed with a strict allowlist: `direction` must be exactly "upgrade" or
"downgrade"; `revision` must match `[A-Za-z0-9_+-]+` — covers every real
Alembic revision shape (head/heads/base, a hex revision id, relative
offsets like -1/+1/head-1) with no shell metacharacters possible.

Every test here proves the fix against the REAL dispatch method
(ChatAgent._execute_tool), not a reimplementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_rm_hardening", repo_path=str(repo))
    return ChatAgent(session)


def _confirm_description(mock_confirm: AsyncMock) -> str:
    call = mock_confirm.await_args
    assert call is not None
    return str(call.kwargs.get("description") or call.args[0])


# ---------------------------------------------------------------------------
# The real exploit, proven to exist (baseline) and proven closed (the fix)
# ---------------------------------------------------------------------------


def test_shell_really_executes_a_semicolon_chained_command(tmp_path: Path) -> None:
    """Baseline proof — not this project's code at all, just confirming
    the real shell behavior the whole rest of this file's fix is built
    around: `shell=True` really does execute a `;`-chained command."""
    marker = tmp_path / "PWNED_baseline"
    subprocess.run(
        f"echo hi; touch {marker}", shell=True, cwd=str(tmp_path), check=True
    )
    assert marker.exists()


@pytest.mark.asyncio
async def test_run_migration_rejects_a_shell_injection_payload_in_revision(
    tmp_path: Path,
) -> None:
    """The real exploit against the real, reachable chat_agent.py
    implementation: a semicolon-chained payload in `revision` must be
    rejected before ever reaching the shell, not merely fail to run."""
    marker = tmp_path / "PWNED_run_migration"
    agent = _agent(tmp_path)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "run_migration",
            {"direction": "upgrade", "revision": f"head; touch {marker}"},
        )

    mock_confirm.assert_not_awaited()  # rejected before ever reaching confirmation
    assert result.startswith("[ERROR]")
    assert not marker.exists()  # the injected command never ran


@pytest.mark.asyncio
async def test_run_migration_rejects_other_shell_metacharacters(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    for payload in [
        "head && echo pwned",
        "head | echo pwned",
        "head`echo pwned`",
        "head$(echo pwned)",
        "head > /tmp/x",
        "head\npwned",
        "-1; rm -rf /",
    ]:
        with patch.object(
            agent, "_confirm", new=AsyncMock(return_value=True)
        ) as mock_confirm:
            result = await agent._execute_tool(
                "run_migration", {"direction": "upgrade", "revision": payload}
            )
        mock_confirm.assert_not_awaited()
        assert result.startswith("[ERROR]"), f"payload not rejected: {payload!r}"


@pytest.mark.asyncio
async def test_run_migration_rejects_an_invalid_direction(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "run_migration", {"direction": "sideways; touch /tmp/x"}
        )
    mock_confirm.assert_not_awaited()
    assert result.startswith("[ERROR]")
    assert "direction must be" in result


# ---------------------------------------------------------------------------
# Regression — every legitimate real Alembic revision shape must still work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision",
    ["head", "heads", "base", "-1", "+1", "head-1", "ae1027a6acf", "ae1027a6acf+2"],
)
async def test_run_migration_accepts_every_real_alembic_revision_shape(
    tmp_path: Path, revision: str
) -> None:
    agent = _agent(tmp_path)
    with (
        patch.object(
            agent, "_confirm", new=AsyncMock(return_value=True)
        ) as mock_confirm,
        patch("app.agents.chat_agent._run_subprocess", return_value="ok") as mock_run,
    ):
        result = await agent._execute_tool(
            "run_migration", {"direction": "upgrade", "revision": revision}
        )

    mock_confirm.assert_awaited_once()
    mock_run.assert_called_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_run_migration_confirmation_still_gates_a_valid_request(
    tmp_path: Path,
) -> None:
    """Regression proof: the real safety mechanism (human confirmation)
    still works for legitimate requests — declining still blocks
    execution, exactly as before this fix."""
    agent = _agent(tmp_path)
    with (
        patch.object(
            agent, "_confirm", new=AsyncMock(return_value=False)
        ) as mock_confirm,
        patch("app.agents.chat_agent._run_subprocess") as mock_run,
    ):
        result = await agent._execute_tool(
            "run_migration", {"direction": "upgrade", "revision": "head"}
        )

    mock_confirm.assert_awaited_once()
    mock_run.assert_not_called()
    assert result == "[CANCELLED] run_migration cancelled by user"


@pytest.mark.asyncio
async def test_run_migration_downgrade_default_revision_still_works(
    tmp_path: Path,
) -> None:
    """Regression proof: the default revision ("-1" for downgrade, "head"
    for upgrade, when the caller omits it) still resolves correctly."""
    agent = _agent(tmp_path)
    with (
        patch.object(
            agent, "_confirm", new=AsyncMock(return_value=True)
        ) as mock_confirm,
        patch("app.agents.chat_agent._run_subprocess", return_value="ok") as mock_run,
    ):
        result = await agent._execute_tool("run_migration", {"direction": "downgrade"})

    mock_confirm.assert_awaited_once()
    description = _confirm_description(mock_confirm)
    assert "downgrade -1" in description
    mock_run.assert_called_once()
    assert result == "ok"
