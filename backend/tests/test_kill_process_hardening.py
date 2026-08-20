"""kill_process tool #49 — tool_enhance.md productionization pass
(2026-08-20).

Real, severe, empirically-verified finding: `process_manager.kill()`
(the single shared implementation both real call sites already used)
sent `os.kill()` to ANY pid at all, with no check that it belonged to a
process the calling session actually spawned via `run_background`.
Proved live: a completely unrelated real `sleep 300` process, never
tracked by the calling session, was genuinely killed. This was a
documented, deliberate decision preserved during a prior refactor, not
an oversight — raised to the user directly (AskUserQuestion); user
chose to close it.

Every test here spawns a REAL OS process via `subprocess.Popen` and
proves the fix (and the still-working legitimate path) against the REAL
dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler), never mocking `os.kill`.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.fleet import process_manager as pm
from app.models.chat import ChatSession
from app.tools.execution.kill_process import KILL_PROCESS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_kill_process_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_kill_process_tool_schema_requires_pid() -> None:
    assert KILL_PROCESS_TOOL["name"] == "kill_process"
    assert KILL_PROCESS_TOOL["input_schema"]["required"] == ["pid"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Pure process_manager.kill() tests
# ---------------------------------------------------------------------------


def test_kill_rejects_an_untracked_real_process() -> None:
    proc = subprocess.Popen(["sleep", "300"])
    try:
        result = pm.kill(proc.pid, "KILL", {})
        assert result.startswith("[ERROR]")
        time.sleep(0.3)
        assert proc.poll() is None, "untracked process must survive"
    finally:
        proc.kill()
        proc.wait()


def test_kill_allows_a_tracked_real_process() -> None:
    proc = subprocess.Popen(["sleep", "300"])
    procs = {proc.pid: proc}
    result = pm.kill(proc.pid, "KILL", procs)
    assert "Sent KILL" in result
    time.sleep(0.3)
    assert proc.poll() is not None, "tracked process must actually be killed"


# ---------------------------------------------------------------------------
# The proven arbitrary-process-kill finding — verified closed on both
# real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_kill_process_rejects_untracked_process(
    tmp_path: Path,
) -> None:
    proc = subprocess.Popen(["sleep", "300"])
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "kill_process", {"pid": proc.pid, "signal": "KILL"}
        )
        assert result.startswith("[ERROR]")
        time.sleep(0.3)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_make_chat_handlers_kill_process_rejects_untracked_process(
    tmp_path: Path,
) -> None:
    proc = subprocess.Popen(["sleep", "300"])
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["kill_process"]({"pid": proc.pid, "signal": "KILL"})
        assert result.startswith("[ERROR]")
        time.sleep(0.3)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# Regression — a real run_background -> kill_process workflow must keep
# working
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_background_then_kill_process_real_workflow(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)

    spawn_result = await agent._execute_tool(
        "run_background", {"command": "sleep 300"}
    )
    assert "Started background process PID" in spawn_result
    pid = int(spawn_result.split("PID")[1].split(":")[0].strip())

    kill_result = await agent._execute_tool(
        "kill_process", {"pid": pid, "signal": "KILL"}
    )
    assert "Sent KILL" in kill_result
