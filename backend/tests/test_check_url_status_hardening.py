"""check_url_status tool #126 — tool_enhance.md productionization pass
(2026-08-26).

Two real, empirically-verified findings, on the one real
implementation (`check_url_status_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A genuine, live SSRF (server-side request forgery) with zero
   protection at all — `urllib.request.urlopen()` was called directly
   on the LLM-controlled `url` with no validation. Proved live: a real
   local HTTP server on 127.0.0.1 was genuinely connected to and its
   response returned.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools #100/#103/#110/#112/#118/#120/#122) — every
   real interactive-chat call fell through to "[ERROR] Unknown tool".

Both are now closed via a shared `check_url_status_handler()` gated by
the same, already-proven-correct `_ssrf_denial_reason()` guard
`fetch_url` uses.
"""

from __future__ import annotations

import http.server
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.check_url_status import (
    CHECK_URL_STATUS_TOOL,
    check_url_status_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_check_url_status_hardening", repo_path=repo)
    return ChatAgent(session)


@contextmanager
def _local_server(port: int) -> Iterator[str]:
    server = http.server.HTTPServer(
        ("127.0.0.1", port), http.server.SimpleHTTPRequestHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_check_url_status_tool_schema() -> None:
    assert CHECK_URL_STATUS_TOOL["name"] == "check_url_status"
    assert CHECK_URL_STATUS_TOOL["input_schema"]["required"] == ["url"]  # type: ignore[index]


def test_check_url_status_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("check_url_status") == 1


# ---------------------------------------------------------------------------
# Finding #1 — genuine, live SSRF with zero protection
# ---------------------------------------------------------------------------


def test_handler_never_connects_to_a_real_local_server(tmp_path: Path) -> None:
    """Real proof, not a string-only check: a genuine local HTTP
    server is started, and the handler must refuse to reach it."""
    with _local_server(18801) as url:
        result = check_url_status_handler({"url": url})
    assert "[POLICY DENIED]" in result
    assert "HTTP 200" not in result


def test_make_chat_handlers_closes_ssrf(tmp_path: Path) -> None:
    with _local_server(18802) as url:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["check_url_status"]({"url": url})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_ssrf(tmp_path: Path) -> None:
    with _local_server(18803) as url:
        agent = _agent(str(tmp_path))
        result = await agent._execute_tool("check_url_status", {"url": url})
    assert "[POLICY DENIED]" in result


def test_handler_blocks_cloud_metadata_endpoint() -> None:
    result = check_url_status_handler(
        {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert "[POLICY DENIED]" in result


def test_handler_blocks_non_http_scheme() -> None:
    result = check_url_status_handler({"url": "file:///etc/passwd"})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "check_url_status", {"url": "http://169.254.169.254/"}
    )
    assert "Unknown tool" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, against a real public URL
# ---------------------------------------------------------------------------


def test_handler_checks_a_real_public_url() -> None:
    result = check_url_status_handler({"url": "https://example.com"})
    assert "HTTP 200" in result


def test_make_chat_handlers_checks_a_real_public_url(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["check_url_status"]({"url": "https://example.com"})
    assert "HTTP 200" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_checks_a_real_public_url(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "check_url_status", {"url": "https://example.com"}
    )
    assert "HTTP 200" in result
