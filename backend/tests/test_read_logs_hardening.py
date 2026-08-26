"""read_logs tool #116 — tool_enhance.md productionization pass
(2026-08-26).

Two real, empirically-verified findings, on FOUR real implementations
(`bf_read_logs` in `make_bug_fix_handlers`, `mon_read_logs` in
`make_monitoring_agent_handlers`, `read_logs` inside
`make_chat_handlers`, and `chat_agent.py`'s own dispatch):

1. A worktree-boundary escape that is a genuine ARBITRARY FILE READ on
   ALL FOUR implementations — `root / path` (or an explicit
   `is_absolute()` branch) silently discarded `root` whenever `path`
   was already absolute, letting the LLM read any file on the host
   readable by the running process.
2. `bf_read_logs`/`mon_read_logs` silently ignored the schema's own
   documented `level` filter and journalctl-by-service-name behavior,
   diverging from their own contract.

Both are now closed via a single shared `read_logs_handler()`
(`check_path_in_worktree()` validation + the full documented
contract), used identically by all four real call sites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_bug_fix_handlers,
    make_chat_handlers,
    make_monitoring_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.read_logs import READ_LOGS_TOOL, read_logs_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_read_logs_hardening", repo_path=repo)
    return ChatAgent(session)


def test_read_logs_tool_schema() -> None:
    assert READ_LOGS_TOOL["name"] == "read_logs"
    assert READ_LOGS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_read_logs_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_logs") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_bug_fix_handlers", make_bug_fix_handlers),
        ("make_monitoring_agent_handlers", make_monitoring_agent_handlers),
        ("make_chat_handlers", make_chat_handlers),
    ],
)
def test_all_factories_close_worktree_escape_read(
    tmp_path: Path, factory_name: str, factory: Any
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_secret.log"
    outside.write_text("SECRET_OUTSIDE_WORKTREE\n")

    handlers = factory(str(repo))
    result = handlers["read_logs"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result, f"{factory_name} did not close the escape"
    assert "SECRET_OUTSIDE_WORKTREE" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_worktree_escape_read(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside_secret.log"
    outside.write_text("SECRET_OUTSIDE_WORKTREE\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("read_logs", {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "SECRET_OUTSIDE_WORKTREE" not in result


def test_handler_closes_worktree_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside_secret.log"
    outside.write_text("SECRET_OUTSIDE_WORKTREE\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = read_logs_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "SECRET_OUTSIDE_WORKTREE" not in result


# ---------------------------------------------------------------------------
# Finding #2 — full documented contract now honored (level filter,
# journalctl-by-service) by all four implementations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [make_bug_fix_handlers, make_monitoring_agent_handlers, make_chat_handlers],
)
def test_all_factories_honor_level_filter(tmp_path: Path, factory: Any) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO: msg1\nERROR: msg2\nINFO: msg3\n")

    handlers = factory(str(tmp_path))
    result = handlers["read_logs"]({"path": "app.log", "level": "ERROR"})
    assert "msg2" in result
    assert "msg1" not in result
    assert "msg3" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all four real
# access paths
# ---------------------------------------------------------------------------


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = read_logs_handler(tmp_path, str(tmp_path), {"path": "missing.log"})
    assert result == "[ERROR] Log file not found: missing.log"


@pytest.mark.parametrize(
    "factory",
    [make_bug_fix_handlers, make_monitoring_agent_handlers, make_chat_handlers],
)
def test_all_factories_read_a_real_log_file(tmp_path: Path, factory: Any) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("hello world\n")

    handlers = factory(str(tmp_path))
    result = handlers["read_logs"]({"path": "app.log"})
    assert "hello world" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_reads_a_real_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("hello world\n")

    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("read_logs", {"path": "app.log"})
    assert "hello world" in result


def test_handler_returns_a_string_with_no_input() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        result = read_logs_handler(Path(td), td, {})
        assert isinstance(result, str)
