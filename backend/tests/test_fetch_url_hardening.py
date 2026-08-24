"""fetch_url tool #86 — tool_enhance.md productionization pass
(2026-08-24).

Two real, empirically-verified findings, both flagged as pending back
in tool #14's own audit and now closed, fixed at the shared
`fetch_url_handler()` in `app.tools.execution.fetch_url`:

1. An unbounded, LLM-controlled `timeout` on two of the three real
   implementations (`make_chat_handlers()`, `chat_agent.py`'s
   dispatch) — a real resource-exhaustion vector, same class already
   fixed for `run_python_snippet` in tool #14.
2. An uncaught `ValueError` on a non-numeric `timeout`, same class as
   tool #78's `git_log`.

SSRF protection (`_ssrf_denial_reason`) was already correct and
unchanged — re-verified live, not assumed.

A secondary, non-security finding: `ae_fetch_url` (`ai_engineer`
agent) previously ignored its own advertised `timeout`/`summarize`
schema fields entirely (hardcoded 10s via `urllib.request`, no
summarize support) — now unified onto the same shared, correct
handler.

Tests here that reach the network use a real, stable domain
(example.com) — matching the existing test suite's own established
pattern for this tool.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_ai_engineer_handlers,
    make_chat_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.fetch_url import FETCH_URL_TOOL, MAX_FETCH_URL_TIMEOUT_SECONDS


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_fetch_url_hardening", repo_path=repo)
    return ChatAgent(session)


def test_fetch_url_tool_schema_requires_url() -> None:
    assert FETCH_URL_TOOL["name"] == "fetch_url"
    assert FETCH_URL_TOOL["input_schema"]["required"] == ["url"]  # type: ignore[index]


def test_fetch_url_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("fetch_url") == 1


# ---------------------------------------------------------------------------
# Finding #1 — unbounded timeout (make_chat_handlers, chat_agent.py)
# ---------------------------------------------------------------------------


def _patch_subprocess_run_spy(monkeypatch, captured: dict) -> None:
    """Replaces subprocess.run with a no-op spy that never touches the
    real network, capturing what fetch_url_handler would have sent it."""
    import subprocess as real_subprocess

    import app.tools.execution.fetch_url as fetch_url_module

    def _spy_run(cmd, **kwargs):
        captured["max_time_value"] = cmd[cmd.index("--max-time") + 1]
        captured["timeout_kwarg"] = kwargs.get("timeout")
        return real_subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(fetch_url_module.subprocess, "run", _spy_run)


def test_make_chat_handlers_clamps_huge_timeout(tmp_path, monkeypatch) -> None:
    captured: dict = {}
    _patch_subprocess_run_spy(monkeypatch, captured)
    handlers = make_chat_handlers(str(tmp_path))
    handlers["fetch_url"]({"url": "http://example.com", "timeout": 999999999})

    assert int(captured["max_time_value"]) <= MAX_FETCH_URL_TIMEOUT_SECONDS
    assert captured["timeout_kwarg"] <= MAX_FETCH_URL_TIMEOUT_SECONDS + 5


@pytest.mark.asyncio
async def test_chat_agent_clamps_huge_timeout(tmp_path, monkeypatch) -> None:
    captured: dict = {}
    _patch_subprocess_run_spy(monkeypatch, captured)
    agent = _agent(str(tmp_path))
    await agent._execute_tool(
        "fetch_url", {"url": "http://example.com", "timeout": 999999999}
    )

    assert int(captured["max_time_value"]) <= MAX_FETCH_URL_TIMEOUT_SECONDS
    assert captured["timeout_kwarg"] <= MAX_FETCH_URL_TIMEOUT_SECONDS + 5


# ---------------------------------------------------------------------------
# Finding #2 — uncaught ValueError on non-numeric timeout (all real
# call sites)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_handles_non_numeric_timeout_gracefully(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "fetch_url", {"url": "http://example.com", "timeout": "not_a_number"}
    )
    assert result.startswith("[ERROR]")  # must not raise


def test_make_chat_handlers_handles_non_numeric_timeout_gracefully(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["fetch_url"](
        {"url": "http://example.com", "timeout": "not_a_number"}
    )
    assert result.startswith("[ERROR]")


def test_ai_engineer_handles_non_numeric_timeout_gracefully(tmp_path) -> None:
    """ae_fetch_url previously ignored `timeout` entirely — now it's
    read, validated, and clamped like every other real call site."""
    handlers = make_ai_engineer_handlers(str(tmp_path))
    result = handlers["fetch_url"](
        {"url": "http://example.com", "timeout": "not_a_number"}
    )
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# SSRF protection — re-verified live as a regression guard, not
# assumed unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_ssrf_blocks_cloud_metadata_endpoint(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "fetch_url", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert "[POLICY DENIED]" in result


def test_ai_engineer_ssrf_blocks_localhost(tmp_path) -> None:
    handlers = make_ai_engineer_handlers(str(tmp_path))
    result = handlers["fetch_url"]({"url": "http://127.0.0.1:8000/"})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Secondary finding — ae_fetch_url now respects its own advertised
# schema fields
# ---------------------------------------------------------------------------


def test_ai_engineer_now_respects_summarize_field_shape(tmp_path) -> None:
    """Not asserting a real LLM call happens — just that the field is
    read at all now (previously silently ignored)."""
    handlers = make_ai_engineer_handlers(str(tmp_path))
    # An unreachable local port fails fast; summarize=True must not
    # itself raise even when there is no content to summarize.
    result = handlers["fetch_url"](
        {"url": "http://127.0.0.1:1", "summarize": True, "timeout": 2}
    )
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths (real network fetch, matching this test file's
# established pattern)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_fetches_real_content() -> None:
    agent = _agent(".")
    result = await agent._execute_tool("fetch_url", {"url": "https://example.com"})
    assert "Example Domain" in result


def test_make_chat_handlers_fetches_real_content() -> None:
    handlers = make_chat_handlers(".")
    result = handlers["fetch_url"]({"url": "https://example.com"})
    assert "Example Domain" in result


def test_ai_engineer_fetches_real_content() -> None:
    """Was urllib.request-based (2000-char cap, no redirects/UA) —
    now the same curl-based implementation as the other two."""
    handlers = make_ai_engineer_handlers(".")
    result = handlers["fetch_url"]({"url": "https://example.com"})
    assert "Example Domain" in result
