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

import logging
import os
import re
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
    """Return error string if URL should be blocked, else None.

    Sol A06 (2026-10-09): the same check as every server-side fetch
    (app.agents.tool_security): IPv4 AND IPv6, every resolved address, and
    an unresolvable host is blocked (it used to be allowed)."""
    if _allow_internal_urls():
        return None
    from app.agents.tool_security import _ssrf_denial_reason

    reason = _ssrf_denial_reason(url)
    return f"Refusing to open {url!r}: {reason}" if reason else None


def _guard_page(page: Any) -> None:
    """Sol A06: every request the page makes — navigation, redirect, script,
    image, iframe, form post, click — is checked, and allowed requests are
    made over our own pinned connection (resolved, checked and connected in
    one step) and handed back to the browser. The browser never resolves a
    name itself, which closes DNS rebinding; redirects come back to the
    browser as 3xx and are checked again as the next request. WebSockets are
    checked before they connect. ALLOW_INTERNAL_BROWSER_URLS=1 turns the
    guard off (explicit operator opt-out)."""
    if _allow_internal_urls():
        return
    page.route(re.compile(r".*"), _route_request)
    page.route_web_socket(re.compile(r".*"), _route_web_socket)


def _route_request(route: Any) -> None:
    from app.agents.tool_security import pinned_request

    req = route.request
    url = str(req.url)
    scheme = urlparse(url).scheme
    if scheme in ("data", "blob", "about"):
        route.continue_()
        return
    try:
        status, headers, body = pinned_request(
            str(req.method),
            url,
            headers=dict(req.all_headers()),
            body=req.post_data_buffer,
        )
    except PermissionError as exc:
        logger.warning("browser request blocked: %s (%s)", url, exc)
        route.abort("blockedbyclient")
        return
    except Exception as exc:
        logger.info("browser request failed: %s (%s)", url, exc)
        route.abort("failed")
        return
    merged: dict[str, str] = {}
    for key, value in headers:
        k = key.lower()
        merged[k] = f"{merged[k]}\n{value}" if k in merged else value
    route.fulfill(status=status, headers=merged, body=body)


def _route_web_socket(ws: Any) -> None:
    if _check_url_safety(str(ws.url).replace("ws", "http", 1)):
        logger.warning("browser websocket blocked: %s", ws.url)
        ws.close()
        return
    ws.connect_to_server()


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
    _guard_page(page)
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


_SHOT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.(png|jpe?g)$", re.I)


def screenshot_path(name: str | None, session_id: str) -> str:
    """Sol A10 (2026-10-09): where a screenshot is written. Always inside
    this browser session's own folder; the caller may only choose a plain
    file name (.png/.jpg). It used to accept any path on the server, so a
    model could overwrite any file the backend can write. Raises ValueError
    for anything else, before the browser is touched."""
    safe_session = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:64] or "default"
    base = os.path.join(tempfile.gettempdir(), "gridiron-screenshots")
    folder = os.path.join(base, safe_session)
    for d in (base, folder):
        if os.path.islink(d):
            raise ValueError("the screenshot folder may not be a symbolic link")
        os.makedirs(d, mode=0o700, exist_ok=True)
    if name is None or not str(name).strip():
        name = f"screenshot_{uuid.uuid4().hex[:8]}.png"
    name = str(name).strip()
    if not _SHOT_NAME.match(name) or ".." in name:
        raise ValueError(
            "a screenshot name must be a plain file name ending in .png or .jpg "
            "(no folders); it is saved in the session's screenshot folder"
        )
    target = os.path.join(folder, name)
    if os.path.islink(target):
        raise ValueError("refusing to write through a symbolic link")
    if os.path.dirname(os.path.realpath(target)) != os.path.realpath(folder):
        raise ValueError("the screenshot would leave the session's folder")
    return target


def _do_screenshot(path: str | None, session_id: str) -> str:
    target = screenshot_path(path, session_id)
    page = _get_page(session_id)
    page.screenshot(path=target)
    return target


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
