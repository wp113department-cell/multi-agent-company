"""browser_* tools — tool_enhance.md productionization pass, tools
#28-#31 + #123-#125 (2026-08-18): browser_click, browser_navigate,
browser_open, browser_type (medium tier) and browser_close,
browser_read_dom, browser_screenshot (low tier).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tools: browser_open, browser_navigate, browser_screenshot, browser_read_dom,
    browser_click, browser_type, browser_close
Old path: app/agents/tools.py (7 schema dicts and the 7
    `browser_*_h` handlers inside `make_chat_handlers()` — no
    chat_agent.py dispatch existed for ANY of them before this pass)
New path: app/tools/browser/browser_tools.py (this file) — 7 `BROWSER_*_TOOL`
    schemas and 7 `browser_*_handler` functions, all thin wrappers around
    the real logic in `app.repo_tools.browser_driver` (untouched — it was
    already correct, including real SSRF protection on
    `browser_open`/`browser_navigate`, verified by reading it directly).
Affected agents: 1 per tool_inventory.json (chat_agent) for each of the 7
    — all 7 are advertised in `CHAT_TOOLS` but chat_agent.py had zero
    dispatch for any of them; every real call to any of these 7 tools has
    always fallen through to "[ERROR] Unknown tool: browser_*".
Affected modules: app/agents/tools.py (compatibility re-export, all 7
    handlers inside `make_chat_handlers()` delegate to the shared
    functions), app/agents/chat_agent.py (gains real dispatch branches
    for all 7 for the first time).
Affected registries: none — app/fleet/tool_manifest.py's ToolManifestEntry
    rows for these are pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    these tools via `handlers["browser_*"](...)`. New tests added: see
    tests/test_browser_tools_hardening.py, including new coverage of
    chat_agent.py's real dispatch for all 7 (didn't exist before —
    nothing to test).

Runtime verification: PASS — see
    backend/docs/tool_productionization/browser_tools.md.
---------------------------------------------------------------------------

Why one file for 7 tools, not 7 files: unlike the docker_* family (tools
#18-#21, each with genuinely distinct validation logic worth its own
file), every one of these 7 tools is a thin, nearly-identical wrapper —
resolve a session id, call the matching `app.repo_tools.browser_driver`
function, format the result — around ONE shared driver module all 7 also
share. Splitting them into 7 files would mean 7 near-empty files
duplicating the same import and the same one-line delegation pattern,
with no real per-tool logic to justify the separation.

Why fixed together in one turn rather than one tracking row at a time:
all 7 share the exact same root cause (advertised in `CHAT_TOOLS`, zero
chat_agent.py dispatch) and the exact same one-line fix (call the
already-correct driver function). Fixing 4 of the 7 (the medium-tier
ones, tools #28-#31) while leaving the other 3 (low-tier, tools
#123-#125) broken would leave the browser tool family in a confusing,
half-working state for no real benefit — the low-tier 3 are exactly as
mechanical to fix as the medium-tier 4.

Real finding (the same "advertised but never dispatched" bug class as
tools #22/#25 — git_tag/semver_bump): verified directly for all 7, a
real call to any of them via `ChatAgent._execute_tool` returned the
generic `"[ERROR] Unknown tool: browser_*"` fallback.

Investigated (not assumed) whether the underlying driver module itself
had any real vulnerability to fix: `browser_open`/`browser_navigate`
already have real, working SSRF protection
(`app.repo_tools.browser_driver._check_url_safety` — resolves the
hostname and blocks private/loopback/link-local ranges unless
`ALLOW_INTERNAL_BROWSER_URLS=1`, confirmed by reading it directly, not
assumed). `browser_screenshot`'s `path` parameter, when explicitly
provided, is passed to Playwright's `page.screenshot(path=...)` with no
worktree-boundary validation — but unlike every other file-write tool
already hardened in this initiative, this tool's own schema and default
behavior are explicitly documented as writing to `/tmp` when `path` is
omitted (not the repo), so "must stay inside the repo" isn't the
obviously-correct policy here the way it was for e.g. `write_file`.
**Logged as a known, deliberately-deferred finding** (see
`docs/tool_productionization/browser_tools.md`'s own "Deferred" section)
rather than blocking this turn's dispatch-gap fix on designing a new
policy for a tool whose own documented contract already departs from
this codebase's usual write-tool convention.
"""

from __future__ import annotations

from typing import Any

from app.repo_tools import browser_driver as _bd

BROWSER_OPEN_TOOL: dict[str, Any] = {
    "name": "browser_open",
    "description": "Open a URL in a headless browser. Returns page title, URL, and status.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to open"}},
        "required": ["url"],
    },
}

BROWSER_NAVIGATE_TOOL: dict[str, Any] = {
    "name": "browser_navigate",
    "description": "Navigate the current browser page to a new URL.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}

BROWSER_SCREENSHOT_TOOL: dict[str, Any] = {
    "name": "browser_screenshot",
    "description": "Take a screenshot of the current page. Saved in this browser session's own screenshot folder; returns the file path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional plain file name ending in .png or .jpg (no folders). Auto-generated if omitted.",
            }
        },
        "required": [],
    },
}

BROWSER_READ_DOM_TOOL: dict[str, Any] = {
    "name": "browser_read_dom",
    "description": "Read the visible text content of the current page, or a specific selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector (optional). If omitted, reads entire body.",
            }
        },
        "required": [],
    },
}

BROWSER_CLICK_TOOL: dict[str, Any] = {
    "name": "browser_click",
    "description": "Click an element by CSS selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of element to click",
            }
        },
        "required": ["selector"],
    },
}

BROWSER_TYPE_TOOL: dict[str, Any] = {
    "name": "browser_type",
    "description": "Type text into an input field identified by a CSS selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["selector", "text"],
    },
}

BROWSER_CLOSE_TOOL: dict[str, Any] = {
    "name": "browser_close",
    "description": "Close the browser session and release resources.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def browser_open_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        result = _bd.browser_open(str(inp["url"]), session_id=session_id)
        if result.get("status") == "blocked":
            return f"[BLOCKED] {result.get('error', 'URL blocked by SSRF guard')}"
        return f"Opened: {result['url']} — title: {result['title']}"
    except Exception as e:
        return f"[ERROR] {e}"


def browser_navigate_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        result = _bd.browser_navigate(str(inp["url"]), session_id=session_id)
        if "error" in result:
            return f"[BLOCKED] {result['error']}"
        return f"Navigated to: {result['url']} — title: {result['title']}"
    except Exception as e:
        return f"[ERROR] {e}"


def browser_screenshot_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        path_out = _bd.browser_screenshot(inp.get("path"), session_id=session_id)
        return f"Screenshot saved: {path_out}"
    except Exception as e:
        return f"[ERROR] {e}"


def browser_read_dom_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        result: str = _bd.browser_read_dom(inp.get("selector"), session_id=session_id)
        return result
    except Exception as e:
        return f"[ERROR] {e}"


def browser_click_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        result: str = _bd.browser_click(str(inp["selector"]), session_id=session_id)
        return result
    except Exception as e:
        return f"[ERROR] {e}"


def browser_type_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        result: str = _bd.browser_type(
            str(inp["selector"]), str(inp["text"]), session_id=session_id
        )
        return result
    except Exception as e:
        return f"[ERROR] {e}"


def browser_close_handler(inp: dict[str, Any], *, session_id: str) -> str:
    try:
        result: str = _bd.browser_close(session_id=session_id)
        return result
    except Exception as e:
        return f"[ERROR] {e}"
