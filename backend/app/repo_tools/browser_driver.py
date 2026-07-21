"""Playwright browser driver.

Fixes vs. previous version:
  1. Playwright's sync API is not thread-safe — every call must happen on the
     same OS thread that created the Playwright/browser objects. The previous
     module-level singleton could be called from whatever thread pool worker
     the async tool-dispatch happened to use, raising greenlet/thread-affinity
     errors under concurrent load. This version pins all Playwright work to one
     dedicated background thread via a single-worker executor.
  2. The previous version used one global _page for the whole process, so two
     concurrent sessions would silently share (and clobber) the same page. This
     version keys pages by session_id so each session gets its own isolated page
     while still sharing one browser process.
  3. Added SSRF guard: browser_open/browser_navigate refuse to navigate to
     private/link-local/loopback IPs unless ALLOW_INTERNAL_BROWSER_URLS=1.
  4. Added browser_close_all() and a max page count to avoid unbounded growth.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright-driver")

_playwright_ctx: Any = None
_browser: Any = None
_pages: dict[str, Any] = {}
_DEFAULT_SESSION = "__default__"
_MAX_PAGES = 25


def _is_headless() -> bool:
    return os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"


def _allow_internal_urls() -> bool:
    return os.environ.get("ALLOW_INTERNAL_BROWSER_URLS", "0") == "1"


def _check_url_safety(url: str) -> str | None:
    """Return error string if URL should be blocked, else None."""
    if _allow_internal_urls():
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Refusing to navigate to non-http(s) scheme: {parsed.scheme!r}"
    host = parsed.hostname
    if not host:
        return "Could not parse hostname from URL"
    try:
        resolved = socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved)
    except (socket.gaierror, ValueError):
        return None
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        return f"Refusing to navigate to internal/private address: {host} -> {ip}"
    return None


def _ensure_browser() -> Any:
    global _playwright_ctx, _browser
    if _browser is not None:
        return _browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed — run: pip install playwright && playwright install chromium"
        )
    _playwright_ctx = sync_playwright().start()
    _browser = _playwright_ctx.chromium.launch(headless=_is_headless())
    return _browser


def _get_page(session_id: str) -> Any:
    browser = _ensure_browser()
    page = _pages.get(session_id)
    if page is not None:
        try:
            _ = page.url
            return page
        except Exception:
            _pages.pop(session_id, None)
    if len(_pages) >= _MAX_PAGES:
        oldest_id = next(iter(_pages))
        try:
            _pages[oldest_id].close()
        except Exception:
            pass
        _pages.pop(oldest_id, None)
    page = browser.new_page()
    _pages[session_id] = page
    return page


def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
    future = _executor.submit(fn, *args, **kwargs)
    return future.result(timeout=90)


def _do_open(url: str, session_id: str) -> dict[str, str]:
    err = _check_url_safety(url)
    if err:
        return {"title": "", "url": url, "status": "blocked", "error": err}
    page = _get_page(session_id)
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    return {"title": page.title(), "url": page.url, "status": "ok"}


def _do_navigate(url: str, session_id: str) -> dict[str, str]:
    err = _check_url_safety(url)
    if err:
        return {"title": "", "url": url, "error": err}
    page = _get_page(session_id)
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    return {"title": page.title(), "url": page.url}


def _do_screenshot(path: str | None, session_id: str) -> str:
    page = _get_page(session_id)
    if path is None:
        path = os.path.join(
            tempfile.gettempdir(), f"screenshot_{uuid.uuid4().hex[:8]}.png"
        )
    page.screenshot(path=path)
    return path


def _do_read_dom(selector: str | None, session_id: str) -> str:
    page = _get_page(session_id)
    if selector:
        try:
            el = page.query_selector(selector)
            return el.inner_text() if el else f"[ERROR] Selector not found: {selector}"
        except Exception as e:
            return f"[ERROR] {e}"
    return str(page.inner_text("body"))


def _do_click(selector: str, session_id: str) -> str:
    page = _get_page(session_id)
    try:
        page.click(selector, timeout=10000)
        return f"Clicked: {selector}"
    except Exception as e:
        return f"[ERROR] {e}"


def _do_type(selector: str, text: str, session_id: str) -> str:
    page = _get_page(session_id)
    try:
        page.fill(selector, text)
        return f"Typed into {selector}"
    except Exception as e:
        return f"[ERROR] {e}"


def _do_close(session_id: str) -> str:
    page = _pages.pop(session_id, None)
    if page is not None:
        try:
            page.close()
        except Exception:
            pass
        return f"Closed browser session: {session_id}"
    return f"No open page for session: {session_id}"


def _do_close_all() -> str:
    global _playwright_ctx, _browser
    for pid in list(_pages.keys()):
        try:
            _pages[pid].close()
        except Exception:
            pass
    _pages.clear()
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright_ctx is not None:
        try:
            _playwright_ctx.stop()
        except Exception:
            pass
        _playwright_ctx = None
    return "All browser sessions closed"


def browser_open(url: str, session_id: str = _DEFAULT_SESSION) -> dict[str, str]:
    return _run(_do_open, url, session_id)  # type: ignore[no-any-return]


def browser_navigate(url: str, session_id: str = _DEFAULT_SESSION) -> dict[str, str]:
    return _run(_do_navigate, url, session_id)  # type: ignore[no-any-return]


def browser_screenshot(
    path: str | None = None, session_id: str = _DEFAULT_SESSION
) -> str:
    return _run(_do_screenshot, path, session_id)  # type: ignore[no-any-return]


def browser_read_dom(
    selector: str | None = None, session_id: str = _DEFAULT_SESSION
) -> str:
    return _run(_do_read_dom, selector, session_id)  # type: ignore[no-any-return]


def browser_click(selector: str, session_id: str = _DEFAULT_SESSION) -> str:
    return _run(_do_click, selector, session_id)  # type: ignore[no-any-return]


def browser_type(selector: str, text: str, session_id: str = _DEFAULT_SESSION) -> str:
    return _run(_do_type, selector, text, session_id)  # type: ignore[no-any-return]


def browser_close(session_id: str = _DEFAULT_SESSION) -> str:
    return _run(_do_close, session_id)  # type: ignore[no-any-return]


def browser_close_all() -> str:
    return _run(_do_close_all)  # type: ignore[no-any-return]
