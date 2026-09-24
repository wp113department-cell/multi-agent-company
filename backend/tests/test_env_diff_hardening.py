"""env_diff tool #135 — tool_enhance.md productionization pass
(2026-09-11).

Three real, empirically-verified findings, on the one real
implementation (`env_diff_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A worktree-boundary escape on both `example` and `actual` — a
   genuine environment-variable-NAME disclosure oracle. Proved live: a
   real key name unique to a file outside the worktree was genuinely
   disclosed.
2. A real robustness gap — an uncaught crash on a real permission
   error. Proved live with a real `chmod 000` file.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

**A real regression caught and fixed during this same turn**: a first
attempt reused `check_path_in_worktree()` wholesale, which also
applies the general secrets/`.env` denylist — reusing it verbatim
broke the tool's own documented DEFAULT behavior outright, since
`.env`/`.env.example` are this tool's own default filenames. Caught
live before being considered complete; fixed with a narrow,
worktree-boundary-only check (`_worktree_boundary_only()`) that omits
the denylist, since this tool only ever discloses key NAMES, never
values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.env_diff import ENV_DIFF_TOOL, env_diff_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_env_diff_hardening", repo_path=repo)
    return ChatAgent(session)


def test_env_diff_tool_schema() -> None:
    assert ENV_DIFF_TOOL["name"] == "env_diff"
    assert ENV_DIFF_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_env_diff_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("env_diff") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape env-variable-name disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_example_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_a = tmp_path / "outside_a.env"
    outside_a.write_text("SECRET_API_KEY=x\n")
    outside_b = tmp_path / "outside_b.env"
    outside_b.write_text("SECRET_API_KEY=x\nEXTRA_OUTSIDE_ONLY_KEY=z\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["env_diff"]({"example": str(outside_a), "actual": str(outside_b)})
    assert "[POLICY DENIED]" in result
    assert "EXTRA_OUTSIDE_ONLY_KEY" not in result


def test_make_chat_handlers_closes_actual_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env.example").write_text("KEY1=\n")
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET_KEY=x\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["env_diff"]({"actual": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "SECRET_KEY" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET_KEY=x\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("env_diff", {"example": str(outside)})
    assert "[POLICY DENIED]" in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET_KEY=x\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = env_diff_handler(repo, str(repo), {"actual": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught crash on a real permission error
# ---------------------------------------------------------------------------


def test_handler_no_longer_crashes_on_permission_error(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEY1=a\n")
    target.chmod(0o000)
    try:
        result = env_diff_handler(tmp_path, str(tmp_path), {})
        assert result.startswith("[ERROR]")
    finally:
        target.chmod(0o644)


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("KEY1=\nKEY2=\n")
    (tmp_path / ".env").write_text("KEY1=a\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("env_diff", {})
    assert "Unknown tool" not in result
    assert "KEY2" in result


# ---------------------------------------------------------------------------
# Regression — the narrow worktree-only check must NOT break the
# tool's own default .env/.env.example usage (the bug caught mid-turn)
# ---------------------------------------------------------------------------


def test_handler_legitimate_default_env_files_not_blocked(tmp_path: Path) -> None:
    """The exact regression caught during this turn: reusing the
    general denylist-including check broke this tool's own documented
    default filenames."""
    (tmp_path / ".env.example").write_text("KEY1=\nKEY2=\n")
    (tmp_path / ".env").write_text("KEY1=a\n")
    result = env_diff_handler(tmp_path, str(tmp_path), {})
    assert "[POLICY DENIED]" not in result
    assert "Missing in .env" in result
    assert "KEY2" in result


def test_handler_reports_no_differences(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("KEY1=\n")
    (tmp_path / ".env").write_text("KEY1=a\n")
    result = env_diff_handler(tmp_path, str(tmp_path), {})
    assert "No differences" in result


def test_handler_reports_extra_keys(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("KEY1=\n")
    (tmp_path / ".env").write_text("KEY1=a\nKEY_EXTRA=b\n")
    result = env_diff_handler(tmp_path, str(tmp_path), {})
    assert "Extra in .env" in result
    assert "KEY_EXTRA" in result


def test_handler_treats_missing_files_as_empty(tmp_path: Path) -> None:
    result = env_diff_handler(tmp_path, str(tmp_path), {})
    assert "No differences" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_reports_real_differences(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("KEY1=\nKEY2=\n")
    (tmp_path / ".env").write_text("KEY1=a\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("env_diff", {})
    assert "Missing in .env" in result
    assert "KEY2" in result
