"""browser_* tools #28-#31 + #123-#125 — tool_enhance.md
productionization pass (2026-08-18).

Real, empirically-verified finding (the same "advertised but never
dispatched" bug class as tools #22/#25 — git_tag/semver_bump): all 7
browser_* tools (browser_open, browser_navigate, browser_screenshot,
browser_read_dom, browser_click, browser_type, browser_close) are
advertised in CHAT_TOOLS, but chat_agent.py had zero dispatch for any of
them. Verified directly: a real call to any of them returned the generic
"[ERROR] Unknown tool: browser_*" fallback before this fix.

The underlying driver (app.repo_tools.browser_driver) was already
correct — real SSRF protection on browser_open/browser_navigate,
verified directly here too, not assumed.

These tests use a real headless Playwright browser (installed in this
environment) against example.com — skipped if Playwright/a browser isn't
available, matching this codebase's own convention for infra-dependent
tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.browser.browser_tools import (
    BROWSER_CLICK_TOOL,
    BROWSER_CLOSE_TOOL,
    BROWSER_NAVIGATE_TOOL,
    BROWSER_OPEN_TOOL,
    BROWSER_READ_DOM_TOOL,
    BROWSER_SCREENSHOT_TOOL,
    BROWSER_TYPE_TOOL,
)

try:
    from app.repo_tools import browser_driver as _bd

    _bd.browser_open("https://example.com")
    _bd.browser_close()
    _HAS_BROWSER = True
except Exception:
    _HAS_BROWSER = False

pytestmark = pytest.mark.skipif(
    not _HAS_BROWSER, reason="requires a real, working Playwright browser"
)


def _agent(repo: Path, session_id: str) -> ChatAgent:
    session = ChatSession(session_id=session_id, repo_path=str(repo))
    return ChatAgent(session)


def test_browser_tool_schemas_have_expected_names() -> None:
    assert BROWSER_OPEN_TOOL["name"] == "browser_open"
    assert BROWSER_NAVIGATE_TOOL["name"] == "browser_navigate"
    assert BROWSER_SCREENSHOT_TOOL["name"] == "browser_screenshot"
    assert BROWSER_READ_DOM_TOOL["name"] == "browser_read_dom"
    assert BROWSER_CLICK_TOOL["name"] == "browser_click"
    assert BROWSER_TYPE_TOOL["name"] == "browser_type"
    assert BROWSER_CLOSE_TOOL["name"] == "browser_close"


# ---------------------------------------------------------------------------
# The real, proven "advertised but never dispatched" gap — verified
# closed for all 7, with a real headless browser end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_browser_tools_full_real_lifecycle(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "td_browser_lifecycle")
    try:
        r_open = await agent._execute_tool(
            "browser_open", {"url": "https://example.com"}
        )
        assert r_open != "[ERROR] Unknown tool: browser_open"
        assert r_open.startswith("Opened:")
        assert "Example Domain" in r_open

        r_nav = await agent._execute_tool(
            "browser_navigate", {"url": "https://example.com"}
        )
        assert r_nav != "[ERROR] Unknown tool: browser_navigate"
        assert r_nav.startswith("Navigated to:")

        r_dom = await agent._execute_tool("browser_read_dom", {})
        assert r_dom != "[ERROR] Unknown tool: browser_read_dom"
        # example.com's body copy is third-party content that changes over
        # time (it went multilingual in 2026 and dropped the heading from the
        # extracted text) — assert on the stable part, not a specific phrase.
        assert not r_dom.startswith("[ERROR]")
        assert "domain" in r_dom.lower()

        r_shot = await agent._execute_tool("browser_screenshot", {})
        assert r_shot != "[ERROR] Unknown tool: browser_screenshot"
        assert r_shot.startswith("Screenshot saved:")
        saved_path = r_shot.removeprefix("Screenshot saved: ").strip()
        assert os.path.exists(saved_path)
        os.unlink(saved_path)

        r_click = await agent._execute_tool(
            "browser_click", {"selector": "#does-not-exist"}
        )
        assert r_click != "[ERROR] Unknown tool: browser_click"
        assert "[ERROR]" in r_click  # real Playwright timeout, not "Unknown tool"

        r_type = await agent._execute_tool(
            "browser_type", {"selector": "#does-not-exist", "text": "hi"}
        )
        assert r_type != "[ERROR] Unknown tool: browser_type"
        assert "[ERROR]" in r_type
    finally:
        r_close = await agent._execute_tool("browser_close", {})
        assert r_close != "[ERROR] Unknown tool: browser_close"
        assert "Closed browser session" in r_close


# ---------------------------------------------------------------------------
# SSRF protection — already correct in the driver, verified end-to-end
# through the real dispatch too
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_browser_open_blocks_cloud_metadata_endpoint(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path, "td_browser_ssrf_1")
    result = await agent._execute_tool(
        "browser_open", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert result.startswith("[BLOCKED]")


@pytest.mark.asyncio
async def test_chat_agent_browser_open_blocks_localhost(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "td_browser_ssrf_2")
    result = await agent._execute_tool(
        "browser_open", {"url": "http://localhost:8000/"}
    )
    assert result.startswith("[BLOCKED]")


@pytest.mark.asyncio
async def test_chat_agent_browser_navigate_blocks_private_ip(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "td_browser_ssrf_3")
    result = await agent._execute_tool(
        "browser_navigate", {"url": "http://192.168.1.1/"}
    )
    assert result.startswith("[BLOCKED]")


# ---------------------------------------------------------------------------
# Regression — make_chat_handlers's own implementations still work
# ---------------------------------------------------------------------------


def test_make_chat_handlers_browser_open_and_close_still_work(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    try:
        result = handlers["browser_open"]({"url": "https://example.com"})
        assert result.startswith("Opened:")
    finally:
        close_result = handlers["browser_close"]({})
        assert "Closed browser session" in close_result
