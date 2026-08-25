"""disk_usage tool #107 — tool_enhance.md productionization pass
(2026-08-25).

Two real, empirically-verified findings:

1. `mon_disk_usage` genuinely diverged from the tool's own documented
   contract two ways: used `df -h` instead of the documented
   `shutil.disk_usage` (a different mechanism, different output
   format than the other two implementations), and defaulted `path`
   to `"/"` (the whole host root filesystem) instead of the documented
   "repo root" — a real information-disclosure-by-default bug.
2. Worktree-boundary escape on all three implementations — none
   validated `path` before it reached `shutil.disk_usage()`/`df`.

Fixed via a shared `disk_usage_handler()`: uses `shutil.disk_usage()`
consistently, defaults to the worktree root when `path` is empty, and
validates `path` via `check_path_in_worktree()`.

All tests here use real files/paths on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_monitoring_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.disk_usage import DISK_USAGE_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_disk_usage_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_disk_usage_tool_schema() -> None:
    assert DISK_USAGE_TOOL["name"] == "disk_usage"
    assert DISK_USAGE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_disk_usage_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("disk_usage") == 1


# ---------------------------------------------------------------------------
# Finding #1 — mon_disk_usage diverged from the documented contract
# ---------------------------------------------------------------------------


def test_monitoring_agent_defaults_to_repo_root_not_host_root(tmp_path: Path) -> None:
    """Previously mon_disk_usage defaulted to "/" (the whole host) —
    now it must default to the repo root, matching the schema's own
    documented "default: repo root" and the other two implementations."""
    handlers = make_monitoring_agent_handlers(str(tmp_path))
    result = handlers["disk_usage"]({})
    assert f"Disk usage for {tmp_path}" in result
    assert result != "Disk usage for /"


def test_monitoring_agent_uses_shutil_format_not_df_table(tmp_path: Path) -> None:
    """Previously mon_disk_usage used `df -h`, producing a raw table
    with a "Filesystem" header — now it must match the documented
    shutil.disk_usage-based "Total/Used/Free GB" format used by the
    other two implementations."""
    handlers = make_monitoring_agent_handlers(str(tmp_path))
    result = handlers["disk_usage"]({})
    assert "Total:" in result
    assert "Used:" in result
    assert "Free:" in result
    assert "Filesystem" not in result


# ---------------------------------------------------------------------------
# Finding #2 — worktree-boundary escape (all three real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("disk_usage", {"path": "/etc"})
    assert "[POLICY DENIED]" in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("monitoring", make_monitoring_agent_handlers),
    ],
)
def test_both_factories_reject_path_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["disk_usage"]({"path": "/etc"})
    assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "disk_usage", {"path": "../../../../../../etc"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_returns_real_disk_usage(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("disk_usage", {})
    assert "Total:" in result
    assert "Used:" in result
    assert "Free:" in result


@pytest.mark.asyncio
async def test_chat_agent_accepts_a_real_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    agent = _agent(tmp_path)
    result = await agent._execute_tool("disk_usage", {"path": "sub"})
    assert "Total:" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_monitoring_agent_handlers],
)
def test_both_factories_return_real_disk_usage(tmp_path: Path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["disk_usage"]({})
    assert "Total:" in result
    assert "Used:" in result
    assert "Free:" in result
