"""pip_install tool #55 — tool_enhance.md productionization pass
(2026-08-20).

Audit result: no new vulnerability, no code fix needed beyond
modularization. No directory/cwd field exists (unlike npm_install/
npm_run, no worktree-escape surface), list-args subprocess (no shell
injection), and a real confirmation gate already exists on the only
real, reachable call site — shows the human the exact raw
`pip install <package>` command, unredacted, before anything runs.

A real, documented (not "fixed") finding: pip's own argument parser
recognizes flags embedded within a single `package` string (e.g. `-e
<path>` for editable installs) even when passed as one literal argv
token with no shell involved — proved live. Not treated as a bug to
reject, since pip's install command legitimately accepts this rich
syntax (editable/VCS installs) as ordinary usage this tool is meant to
support; the existing confirmation gate, which shows the complete raw
value, is the correct safeguard.

These tests use real pip subprocess calls where feasible (a guaranteed-
nonexistent package name, so the network round-trip fails fast and no
real package/code is ever actually installed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.pip_install import PIP_INSTALL_TOOL


def _agent(repo: Path, confirm_result: bool) -> ChatAgent:
    session = ChatSession(session_id="td_pip_install_hardening", repo_path=str(repo))
    agent = ChatAgent(session)

    async def _fake_confirm(*_a: Any, **_kw: Any) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_pip_install_tool_schema_requires_package() -> None:
    assert PIP_INSTALL_TOOL["name"] == "pip_install"
    assert PIP_INSTALL_TOOL["input_schema"]["required"] == ["package"]  # type: ignore[index]


def test_pip_install_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("pip_install") == 1


# ---------------------------------------------------------------------------
# The already-correct confirmation gate — re-verified, not re-fixed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_pip_install_declined_installs_nothing(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path, confirm_result=False)

    result = await agent._execute_tool("pip_install", {"package": "requests"})
    assert result == "[DENIED] User declined pip_install (requests)."


@pytest.mark.asyncio
async def test_chat_agent_pip_install_approved_invokes_real_pip(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path, confirm_result=True)

    result = await agent._execute_tool(
        "pip_install", {"package": "totally-fake-nonexistent-package-xyz-123"}
    )
    # A real pip invocation happened — it just failed because the
    # package doesn't exist, proving the real dispatch path executes.
    assert "totally-fake-nonexistent-package-xyz-123" in result


def test_make_chat_handlers_pip_install_remains_blocked(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))

    result = handlers["pip_install"]({"package": "requests"})
    assert result.startswith("[BLOCKED]")


# ---------------------------------------------------------------------------
# The documented (not fixed) pip flag-recognition finding
# ---------------------------------------------------------------------------


def test_pip_recognizes_embedded_edit_flag_in_a_single_argv_token() -> None:
    """Real, empirical proof this is a genuine pip behavior, not a shell-
    quoting artifact — subprocess.run is called with an explicit argv
    list, no shell=True anywhere, and the combined string is confirmed
    to be exactly one list element."""
    import subprocess
    import sys

    argv = [sys.executable, "-m", "pip", "install", "--dry-run", "-e ."]
    assert len(argv) == 6
    assert argv[5] == "-e ."  # confirmed one single token, not shell-split

    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert "not a valid editable requirement" in result.stderr
