"""Singleton Playwright browser driver — one browser instance per process."""
from __future__ import annotations

import os
import uuid
import tempfile
from typing import Any

# Lazy import so the module can be imported even when playwright is not yet installed
_playwright_ctx: Any = None
_browser: Any = None
_page: Any = None


def _is_headless() -> bool:
    return os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"


def _ensure_page() -> Any:
    global _playwright_ctx, _browser, _page
    if _page is not None:
        return _page
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright not installed — run: pip install playwright && playwright install chromium")
    _playwright_ctx = sync_playwright().start()
    _browser = _playwright_ctx.chromium.launch(headless=_is_headless())
    _page = _browser.new_page()
    return _page


def browser_open(url: str) -> dict[str, str]:
    page = _ensure_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    return {"title": page.title(), "url": page.url, "status": "ok"}


def browser_navigate(url: str) -> dict[str, str]:
    page = _ensure_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    return {"title": page.title(), "url": page.url}


def browser_screenshot(path: str | None = None) -> str:
    page = _ensure_page()
    if path is None:
        path = os.path.join(tempfile.gettempdir(), f"screenshot_{uuid.uuid4().hex[:8]}.png")
    page.screenshot(path=path)
    return path


def browser_read_dom(selector: str | None = None) -> str:
    page = _ensure_page()
    if selector:
        try:
            el = page.query_selector(selector)
            return el.inner_text() if el else f"[ERROR] Selector not found: {selector}"
        except Exception as e:
            return f"[ERROR] {e}"
    return page.inner_text("body")


def browser_click(selector: str) -> str:
    page = _ensure_page()
    try:
        page.click(selector, timeout=10000)
        return f"Clicked: {selector}"
    except Exception as e:
        return f"[ERROR] {e}"


def browser_type(selector: str, text: str) -> str:
    page = _ensure_page()
    try:
        page.fill(selector, text)
        return f"Typed into {selector}"
    except Exception as e:
        return f"[ERROR] {e}"


def browser_close() -> str:
    global _playwright_ctx, _browser, _page
    if _browser is not None:
        _browser.close()
        _browser = None
        _page = None
    if _playwright_ctx is not None:
        _playwright_ctx.stop()
        _playwright_ctx = None
    return "Browser closed"
