"""run_linter tool #101 — tool_enhance.md productionization pass
(2026-08-25).

Four real, empirically-verified findings across the four real
implementations:

1. The most severe: a genuine, direct shell-injection (arbitrary
   command execution) on `chat_agent.py`'s dispatch — `lint_path` was
   interpolated completely unquoted into a `shell=True` command.
2. A real confirmation/opt-in bypass on `make_chat_handlers`'
   `run_linter` — `path="--fix"` bypassed the schema's own
   default-`False` `fix` field and genuinely rewrote a real file
   (`shlex.quote()` protects the shell, not ruff's own flag parser).
3. `sr_run_linter`/`td_run_linter` were completely broken for every
   real call (an invalid `--output-format=text` value) and ignored
   `tool`/`fix` entirely.
4. `tool="eslint"` was a valid schema enum value no implementation
   ever actually supported.

Fixed via a shared `run_linter_handler()` using list-args subprocess
calls only (no `shell=True` anywhere), a `path` validator (rejects
flag-shaped values + worktree-boundary check), a corrected ruff
invocation, and real eslint support.

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
    make_style_reviewer_handlers,
    make_tech_debt_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.run_linter import RUN_LINTER_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_run_linter_hardening", repo_path=str(repo))
    return ChatAgent(session)


def _write_lintable_file(repo: Path, name: str = "bad.py") -> Path:
    f = repo / name
    f.write_text("import os\nx=1\n")
    return f


def test_run_linter_tool_schema() -> None:
    assert RUN_LINTER_TOOL["name"] == "run_linter"
    assert "eslint" in RUN_LINTER_TOOL["input_schema"]["properties"]["tool"]["enum"]  # type: ignore[index]


def test_run_linter_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("run_linter") == 1


# ---------------------------------------------------------------------------
# Finding #1 — shell injection (chat_agent.py dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_shell_injection_via_path(tmp_path: Path) -> None:
    _write_lintable_file(tmp_path)
    marker = tmp_path.parent / "run_linter_hardening_PWNED_marker.txt"
    if marker.exists():
        marker.unlink()
    agent = _agent(tmp_path)
    payload = f"; touch {marker}; echo x"
    result = await agent._execute_tool("run_linter", {"tool": "ruff", "path": payload})
    assert not marker.exists(), "shell injection must not execute a real command"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Finding #2 — --fix flag-collision bypasses the fix=False default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_fix_flag_via_path(tmp_path: Path) -> None:
    f = _write_lintable_file(tmp_path)
    before = f.read_text()
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "run_linter", {"tool": "ruff", "path": "--fix", "fix": False}
    )
    assert "[ERROR]" in result
    assert f.read_text() == before, "file must not be rewritten when fix=False"


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("style_reviewer", make_style_reviewer_handlers),
        ("tech_debt", make_tech_debt_agent_handlers),
    ],
)
def test_all_three_factories_reject_fix_flag_via_path(
    tmp_path: Path, factory_name: str, factory
) -> None:
    f = _write_lintable_file(tmp_path)
    before = f.read_text()
    handlers = factory(str(tmp_path))
    result = handlers["run_linter"]({"tool": "ruff", "path": "--fix", "fix": False})
    assert "[ERROR]" in result, f"{factory_name} did not reject the flag-shaped path"
    assert f.read_text() == before


def test_legitimate_fix_true_still_works(tmp_path: Path) -> None:
    """The real, intended fix=True capability must still work when the
    caller genuinely opts in — this is not a regression to close."""
    f = _write_lintable_file(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_linter"]({"tool": "ruff", "fix": True})
    assert "fixed" in result.lower() or "clean" in result.lower()
    assert "import os" not in f.read_text()


# ---------------------------------------------------------------------------
# Finding #3 — sr_/td_ were totally broken (invalid --output-format)
# ---------------------------------------------------------------------------


def test_style_reviewer_run_linter_actually_works(tmp_path: Path) -> None:
    _write_lintable_file(tmp_path)
    handlers = make_style_reviewer_handlers(str(tmp_path))
    result = handlers["run_linter"]({"tool": "ruff"})
    assert "invalid value" not in result.lower()
    assert "F401" in result or "unused" in result.lower()


def test_tech_debt_run_linter_actually_works(tmp_path: Path) -> None:
    _write_lintable_file(tmp_path)
    handlers = make_tech_debt_agent_handlers(str(tmp_path))
    result = handlers["run_linter"]({"tool": "ruff"})
    assert "invalid value" not in result.lower()
    assert "F401" in result or "unused" in result.lower()


def test_style_reviewer_honors_tool_field(tmp_path: Path) -> None:
    """Previously sr_run_linter hardcoded ruff regardless of `tool` —
    now it must honor mypy too."""
    (tmp_path / "typed.py").write_text("x: int = 'not an int'\n")
    handlers = make_style_reviewer_handlers(str(tmp_path))
    result = handlers["run_linter"]({"tool": "mypy"})
    assert "=== mypy ===" in result
    assert "=== ruff ===" not in result


# ---------------------------------------------------------------------------
# Finding #4 — eslint was documented but never implemented
# ---------------------------------------------------------------------------


def test_eslint_no_longer_returns_unknown_linter_error(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_linter"]({"tool": "eslint"})
    assert "Unknown linter" not in result
    assert "=== eslint ===" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all four real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_runs_real_ruff_check(tmp_path: Path) -> None:
    _write_lintable_file(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("run_linter", {"tool": "ruff"})
    assert "=== ruff ===" in result
    assert "F401" in result or "unused" in result.lower()


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_style_reviewer_handlers, make_tech_debt_agent_handlers],
)
def test_all_three_factories_run_real_ruff_check(tmp_path: Path, factory) -> None:
    _write_lintable_file(tmp_path)
    handlers = factory(str(tmp_path))
    result = handlers["run_linter"]({"tool": "ruff"})
    assert "F401" in result or "unused" in result.lower()


def test_worktree_escape_via_path_rejected(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_linter"]({"tool": "ruff", "path": "/etc"})
    assert "[POLICY DENIED]" in result
