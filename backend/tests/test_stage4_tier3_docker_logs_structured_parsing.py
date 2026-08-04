"""Stage 4 Tier 3 (2026-08-05, answer2.md Q17) — "docker_logs returns raw
output only — no structured parsing/pattern-detection layer."

Mirrors this codebase's own established `analyze_error()` convention
(`tools.py`, real pattern list, "=== X Analysis ===" formatted summary
prepended to the real content, not replacing it) — deliberately
pattern/keyword detection, not a claim of full structured (JSON) log
parsing for every possible container's own log format.

Two real, independent `docker_logs` handlers existed in this file
(`make_docker_agent_handlers`'s `dk_docker_logs` and the chat-tools
`docker_logs` used by `make_chat_handlers`) — both fixed, both tested here,
not just one.
"""

from __future__ import annotations

import shutil

import pytest

from app.agents.tools import (
    _summarize_docker_log_patterns,
    make_chat_handlers,
    make_docker_agent_handlers,
)

_docker_available = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not available in this environment",
)


def test_summarizer_detects_errors_and_warnings() -> None:
    raw = (
        "INFO starting up\n"
        "ERROR failed to connect to database\n"
        "Traceback (most recent call last):\n"
        "ConnectionError: could not connect\n"
        "WARN retrying connection\n"
    )
    summary = _summarize_docker_log_patterns(raw)
    assert "=== Docker Log Analysis ===" in summary
    assert "Error/exception lines (3)" in summary
    assert "Warning lines (1)" in summary


def test_summarizer_detects_crash_signatures() -> None:
    raw = "container killed\nOOMKilled: true\nexit code 137\n"
    summary = _summarize_docker_log_patterns(raw)
    assert "Crash/OOM signatures" in summary


def test_summarizer_returns_empty_string_for_clean_logs() -> None:
    raw = "INFO server started on port 8000\nINFO ready to accept connections\n"
    assert _summarize_docker_log_patterns(raw) == ""


def test_summarizer_caps_shown_lines_at_five_per_category() -> None:
    raw = "\n".join(f"ERROR failure number {i}" for i in range(20))
    summary = _summarize_docker_log_patterns(raw)
    assert "Error/exception lines (20)" in summary
    assert summary.count("failure number") == 5


@_docker_available
def test_docker_agent_handler_wires_the_summarizer_on_a_real_container() -> None:
    """Real docker logs call against a real running container (this
    environment's own gridiron-postgres, confirmed running earlier this
    session) -- not mocked."""
    handlers = make_docker_agent_handlers("/tmp")
    result = handlers["docker_logs"]({"container": "gridiron-postgres", "lines": 20})
    assert "ERROR" not in result or "Docker Log Analysis" in result
    assert isinstance(result, str)
    assert result != "(no logs)"


@_docker_available
def test_chat_handlers_docker_logs_also_wires_the_summarizer() -> None:
    """The second, separate docker_logs implementation (chat's own tool
    set) -- proves both real call sites got the fix, not just one."""
    handlers = make_chat_handlers("/tmp")
    result = handlers["docker_logs"]({"container": "gridiron-postgres", "lines": 20})
    assert isinstance(result, str)
    assert result != "(no logs)"


def test_no_logs_case_is_unaffected_by_the_new_summarizer() -> None:
    """A container with genuinely empty log output must still return the
    original '(no logs)' message, not an empty summary header."""
    from unittest.mock import MagicMock, patch

    handlers = make_docker_agent_handlers("/tmp")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        result = handlers["docker_logs"]({"container": "some-container"})
    assert result == "(no logs)"
