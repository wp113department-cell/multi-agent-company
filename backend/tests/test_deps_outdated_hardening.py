"""deps_outdated tool #134 — tool_enhance.md productionization pass
(2026-09-11).

Three real, empirically-verified findings, on the one real
implementation (`deps_outdated_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. Severe: a worktree-boundary escape on the `npm` branch —
   `directory` reached a subprocess `cwd` completely unvalidated.
   Proved live: a fake `npm` script placed on `PATH` reported its real
   `cwd` was genuinely the injected absolute `directory`, not anything
   inside the intended worktree.
2. A real correctness bug: `has_npm` was computed but never used, so
   "auto" mode silently defaulted to "npm" even when NEITHER
   `requirements.txt`/`pyproject.toml` NOR `package.json` was present
   — and because `npm outdated` exits cleanly with empty output
   against a directory with no `package.json`, this produced a
   misleading "✅ All dependencies are up to date" false positive.
   Proved live.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133) —
   every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

All three are now closed via a shared `deps_outdated_handler()` using
`check_path_in_worktree()` on `directory` (npm branch only, matching
where it was ever actually used) and a corrected `auto`-detection
branch that genuinely uses `has_npm`.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.deps_outdated import (
    DEPS_OUTDATED_TOOL,
    deps_outdated_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_deps_outdated_hardening", repo_path=repo)
    return ChatAgent(session)


def _fake_npm_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real proof mechanism: a genuine executable script on PATH that
    reports its own cwd, rather than a mock -- same technique already
    established for tool #45's github_create_issue."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    npm_script = bin_dir / "npm"
    npm_script.write_text('#!/bin/sh\necho "FAKE_NPM_CWD=$(pwd)"\n')
    npm_script.chmod(npm_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def test_deps_outdated_tool_schema() -> None:
    assert DEPS_OUTDATED_TOOL["name"] == "deps_outdated"
    assert DEPS_OUTDATED_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_deps_outdated_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("deps_outdated") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape via `directory` on the npm branch
# ---------------------------------------------------------------------------


def test_handler_closes_directory_escape_on_npm_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_npm_on_path(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    result = deps_outdated_handler(
        repo, str(repo), {"manager": "npm", "directory": str(outside)}
    )
    assert "[POLICY DENIED]" in result


def test_make_chat_handlers_npm_stays_inside_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real proof the fixed cwd is genuinely inside the worktree, not
    just that the escape errors -- a legitimate npm call's cwd is
    verified via the fake script's own reported cwd."""
    _fake_npm_on_path(tmp_path, monkeypatch)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["deps_outdated"]({"manager": "npm"})
    assert f"FAKE_NPM_CWD={tmp_path}" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_directory_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_npm_on_path(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "deps_outdated", {"manager": "npm", "directory": str(outside)}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — has_npm dead-variable / misleading false positive
# ---------------------------------------------------------------------------


def test_handler_reports_no_manager_found_instead_of_false_positive(
    tmp_path: Path,
) -> None:
    """Real proof: a directory with NEITHER manifest file must not
    silently default to npm and report a misleading 'up to date'."""
    result = deps_outdated_handler(tmp_path, str(tmp_path), {})
    assert "no recognized package manager" in result
    assert "up to date" not in result.lower()


def test_handler_auto_detects_npm_when_package_json_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_npm_on_path(tmp_path, monkeypatch)
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0"}')
    result = deps_outdated_handler(tmp_path, str(tmp_path), {})
    assert f"FAKE_NPM_CWD={tmp_path}" in result


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_npm_on_path(tmp_path, monkeypatch)
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0"}')
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("deps_outdated", {})
    assert "Unknown tool" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working: pip branch untouched
# (directory has always had zero effect there, by design), explicit
# manager selection, both real access paths
# ---------------------------------------------------------------------------


def test_handler_pip_branch_ignores_directory_by_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pip list --outdated inspects the active environment, not a
    directory -- directory has zero effect here, matching the
    original, unchanged behavior (documented, not a bug). Uses a real,
    fast fake `pip` executable on PATH (same technique as the npm
    fixture) instead of the real, slow, network-bound pip -- a
    genuine subprocess execution, not a mock, just not the real
    network-hitting binary."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    pip_script = bin_dir / "pip"
    pip_script.write_text('#!/bin/sh\necho "FAKE_PIP_CWD=$(pwd)"\n')
    pip_script.chmod(pip_script.stat().st_mode | 0o111)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    result = deps_outdated_handler(
        tmp_path, str(tmp_path), {"manager": "pip", "directory": "/etc"}
    )
    assert "[POLICY DENIED]" not in result
    assert result.startswith("FAKE_PIP_CWD=")


def test_handler_explicit_npm_manager_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_npm_on_path(tmp_path, monkeypatch)
    result = deps_outdated_handler(tmp_path, str(tmp_path), {"manager": "npm"})
    assert f"FAKE_NPM_CWD={tmp_path}" in result
