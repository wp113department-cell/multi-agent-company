"""Gap-closure Day 23 (Stage 1.3, answers.md) — proves delete_chat_agent()
(app/agents/chat_agent.py) actually terminates a session's live background
processes on close, instead of just letting the Popen objects (and the
real OS processes they wrap) become unreachable garbage. Uses a real
subprocess.Popen, not a mock, so proc.terminate() is genuinely exercised.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from app.agents import chat_agent as ca
from app.fleet import bg_process_registry as reg


def test_delete_chat_agent_terminates_its_live_background_processes(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "bg-processes.json"

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], text=True
    )
    try:
        agent = ca.ChatAgent.__new__(ca.ChatAgent)
        agent._background_processes = {proc.pid: proc}
        session_id = "test-session-day23"
        ca._chat_agents[session_id] = agent

        with patch.object(reg, "_registry_path", return_value=registry_path):
            reg.register(pid=proc.pid, command="sleep 60", cwd=str(tmp_path))
            ca.delete_chat_agent(session_id)

        assert session_id not in ca._chat_agents

        deadline = time.monotonic() + 5.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "session close must terminate its own process"

        import json

        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert (
            str(proc.pid) not in data
        ), "registry entry must be removed on session close"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_delete_chat_agent_on_an_unknown_session_id_is_a_safe_no_op() -> None:
    ca.delete_chat_agent("does-not-exist")  # must not raise
