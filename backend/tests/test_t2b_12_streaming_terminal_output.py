"""T2-B9/#12 (2026-09-24, GRIDIRON_PARTIAL "Monitor streaming output (live,
mid-command)") — user-approved next build after all 10 T2-B batches closed.

Real gap this closes: `policy/sandbox.py::run_sandboxed()` was a pure
buffer-then-return `subprocess.run(capture_output=True)` — an agent's `bash`
tool call in the interactive chat session showed NOTHING until the whole
command finished, no matter how long it ran. Real chunk-by-chunk proof (not
mocked) that output now arrives progressively is in
`test_run_sandboxed_streaming.py`; this file proves the higher-level wiring:
the chat session's own `bash` dispatch pushes real `terminal_output` SSE
events correlated to the right `tool_use_id`, behind a feature flag
(default OFF per the audit's own explicit plan), with zero change to the
tool's own return value either way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.config import get_settings
from app.models.chat import ChatSession


def _drain(session: ChatSession) -> list[dict]:
    events = []
    while not session._queue.empty():
        events.append(session._queue.get_nowait())
    return events


@pytest.mark.asyncio
async def test_streaming_disabled_by_default_pushes_no_terminal_output(
    tmp_path: Path,
) -> None:
    assert get_settings().bash_sandbox_streaming_enabled is False
    session = ChatSession(session_id="t2b12_default_off", repo_path=str(tmp_path))
    agent = ChatAgent(session)

    out = await agent._execute_tool("bash", {"command": "echo one; echo two"})

    assert "one" in out and "two" in out
    events = _drain(session)
    assert all(e.get("type") != "terminal_output" for e in events)


@pytest.mark.asyncio
async def test_streaming_enabled_pushes_real_terminal_output_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_streaming_enabled", True)

    session = ChatSession(session_id="t2b12_streaming_on", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    agent._current_tool_use_id = "tu_test_12345"

    out = await agent._execute_tool(
        "bash", {"command": "echo first; echo second; echo third >&2"}
    )

    assert "first" in out and "second" in out and "third" in out

    events = _drain(session)
    terminal_events = [e for e in events if e.get("type") == "terminal_output"]
    assert len(terminal_events) >= 3

    # Every event correlates to the real tool_use_id, so the frontend can
    # attach live output to the right in-progress tool call.
    assert all(e["tool_use_id"] == "tu_test_12345" for e in terminal_events)

    stdout_chunks = "".join(
        e["chunk"] for e in terminal_events if e["stream"] == "stdout"
    )
    stderr_chunks = "".join(
        e["chunk"] for e in terminal_events if e["stream"] == "stderr"
    )
    assert "first" in stdout_chunks and "second" in stdout_chunks
    assert "third" in stderr_chunks

    # Order preserved within a stream — first echoed line arrives before
    # the second in the pushed event sequence.
    stdout_events = [e for e in terminal_events if e["stream"] == "stdout"]
    assert stdout_events[0]["chunk"].strip() == "first"
    assert stdout_events[1]["chunk"].strip() == "second"


@pytest.mark.asyncio
async def test_streaming_enabled_does_not_change_the_final_return_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool's own return value must be byte-for-byte the same whether
    streaming is on or off — on_output is purely a side channel."""
    settings = get_settings()

    session_off = ChatSession(session_id="t2b12_cmp_off", repo_path=str(tmp_path))
    agent_off = ChatAgent(session_off)
    monkeypatch.setattr(settings, "bash_sandbox_streaming_enabled", False)
    out_off = await agent_off._execute_tool("bash", {"command": "echo same-output"})

    session_on = ChatSession(session_id="t2b12_cmp_on", repo_path=str(tmp_path))
    agent_on = ChatAgent(session_on)
    monkeypatch.setattr(settings, "bash_sandbox_streaming_enabled", True)
    out_on = await agent_on._execute_tool("bash", {"command": "echo same-output"})

    assert out_off == out_on


@pytest.mark.asyncio
async def test_streaming_survives_a_failing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_streaming_enabled", True)

    session = ChatSession(session_id="t2b12_failing_cmd", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    agent._current_tool_use_id = "tu_fail_case"

    out = await agent._execute_tool("bash", {"command": "echo before-failure; exit 1"})

    assert "before-failure" in out
    assert "[exit 1]" in out
    events = _drain(session)
    terminal_events = [e for e in events if e.get("type") == "terminal_output"]
    assert any("before-failure" in e["chunk"] for e in terminal_events)
