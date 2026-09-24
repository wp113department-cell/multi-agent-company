"""secrets_scan tool #102 — tool_enhance.md productionization pass
(2026-08-25).

Two real, empirically-verified findings:

1. Worktree-boundary escape + real content disclosure on all three
   real implementations — none validated `directory` before it reached
   the canonical `_scan_directory_for_secrets()` scanner.
2. The most severe finding: a genuine, direct shell-injection on
   `chat_agent.py`'s dispatch, which maintained its OWN, third,
   independently-drifted regex list (never migrated onto the canonical
   scanner despite AUDIT_Q_BATCH11 §96 unifying the other two years
   earlier) and interpolated the directory field completely unquoted
   into a shell=True grep command.

Fixed via a shared `secrets_scan_handler()`: `check_path_in_worktree()`
closes finding #1; delegating `chat_agent.py`'s dispatch onto this same
shared handler (the canonical scanner, list-args only) closes finding
#2.

All tests here use real files/subprocess calls on disk — nothing is
mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_security_reviewer_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.secrets_scan import SECRETS_SCAN_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_secrets_scan_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_secrets_scan_tool_schema() -> None:
    assert SECRETS_SCAN_TOOL["name"] == "secrets_scan"
    assert SECRETS_SCAN_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_secrets_scan_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("secrets_scan") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (all three real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_directory_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "secrets_scan_hardening_outside"
    outside.mkdir(exist_ok=True)
    (outside / "config.py").write_text(
        'api_key = "sk-abcdefghijklmnopqrstuvwx1234567890"\n'
    )
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("secrets_scan", {"directory": str(outside)})
        assert "[POLICY DENIED]" in result
    finally:
        (outside / "config.py").unlink()
        outside.rmdir()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("security_reviewer", make_security_reviewer_handlers),
    ],
)
def test_both_factories_reject_directory_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"secrets_scan_hardening_outside_{factory_name}"
    outside.mkdir(exist_ok=True)
    (outside / "config.py").write_text(
        'api_key = "sk-abcdefghijklmnopqrstuvwx1234567890"\n'
    )
    try:
        handlers = factory(str(tmp_path))
        result = handlers["secrets_scan"]({"directory": str(outside)})
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
    finally:
        (outside / "config.py").unlink()
        outside.rmdir()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "secrets_scan", {"directory": "../../../../../../etc"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — genuine shell injection (chat_agent.py dispatch only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_shell_injection_via_directory(tmp_path: Path) -> None:
    marker = tmp_path.parent / "secrets_scan_hardening_PWNED_marker.txt"
    if marker.exists():
        marker.unlink()
    agent = _agent(tmp_path)
    payload = f"; touch {marker}; echo x"
    result = await agent._execute_tool("secrets_scan", {"directory": payload})
    assert not marker.exists(), "shell injection must not execute a real command"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all three real access paths, including the canonical detection set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_detects_real_secret(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        'api_key = "sk-abcdefghijklmnopqrstuvwx1234567890"\n'
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("secrets_scan", {})
    assert "bad.py" in result
    assert "⚠️" in result


@pytest.mark.asyncio
async def test_chat_agent_clean_repo_reports_ok(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("x = 1\nprint('hello')\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("secrets_scan", {})
    assert "✅" in result or "No hardcoded" in result


@pytest.mark.asyncio
async def test_chat_agent_detects_pem_header(tmp_path: Path) -> None:
    """PEM-header detection is part of the canonical scanner's coverage
    but was never in chat_agent.py's own independent regex list before
    this fix — a real, empirically-verified coverage improvement, not
    just a security patch."""
    (tmp_path / "key.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIExyz\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("secrets_scan", {})
    assert "key.pem" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_security_reviewer_handlers],
)
def test_both_factories_detect_real_secret(tmp_path: Path, factory) -> None:
    (tmp_path / "bad.py").write_text(
        'api_key = "sk-abcdefghijklmnopqrstuvwx1234567890"\n'
    )
    handlers = factory(str(tmp_path))
    result = handlers["secrets_scan"]({})
    assert "bad.py" in result
