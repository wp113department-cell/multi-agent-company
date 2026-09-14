"""http_request tool #155 — tool_enhance.md productionization pass
(2026-09-14).

Two real, empirically-verified findings on the one real
implementation (`http_request_h` inside `make_chat_handlers`).

1. A real SSRF vector, including local-file disclosure via the
   `file://` scheme, and full exposure to internal-network SSRF (no
   protection at all, unlike sibling tools `fetch_url`/
   `check_url_status`, which already use the shared
   `_ssrf_denial_reason()` guard).
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `http_request_handler()` using the
same `_ssrf_denial_reason()` guard `fetch_url`/`check_url_status`
already use.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.integrations.http_request import (
    HTTP_REQUEST_TOOL,
    http_request_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_http_request_hardening", repo_path=repo)
    return ChatAgent(session)


def test_http_request_tool_schema() -> None:
    assert HTTP_REQUEST_TOOL["name"] == "http_request"
    assert HTTP_REQUEST_TOOL["input_schema"]["required"] == ["method", "url"]  # type: ignore[index]


def test_http_request_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("http_request") == 1


# ---------------------------------------------------------------------------
# Finding #1 — SSRF (file:// local-file-disclosure + internal-network SSRF)
# ---------------------------------------------------------------------------


class TestSsrfBlocked:
    def test_direct_handler_file_scheme_blocked(self) -> None:
        out = http_request_handler({"method": "GET", "url": "file:///etc/hostname"})
        assert "POLICY DENIED" in out
        # Must never disclose real local file content.
        assert "hostname" not in out.lower() or "resolves" in out.lower()

    def test_direct_handler_cloud_metadata_endpoint_blocked(self) -> None:
        out = http_request_handler(
            {"method": "GET", "url": "http://169.254.169.254/latest/meta-data/"}
        )
        assert "POLICY DENIED" in out

    def test_direct_handler_localhost_blocked(self) -> None:
        out = http_request_handler(
            {"method": "GET", "url": "http://localhost:19999/test"}
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_file_scheme_blocked(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["http_request"]({"method": "GET", "url": "file:///etc/hostname"})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_file_scheme_blocked(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "http_request", {"method": "GET", "url": "file:///etc/hostname"}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "http_request", {"method": "GET", "url": "https://example.com"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "POLICY DENIED" not in out
        assert "HTTP 200" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real external HTTPS, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_external_request(self) -> None:
        out = http_request_handler({"method": "GET", "url": "https://example.com"})
        assert "POLICY DENIED" not in out
        assert "HTTP 200" in out

    def test_make_chat_handlers_real_external_request(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["http_request"]({"method": "GET", "url": "https://example.com"})
        assert "POLICY DENIED" not in out
        assert "HTTP 200" in out
