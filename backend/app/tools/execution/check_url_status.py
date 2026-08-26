"""check_url_status tool — tool_enhance.md productionization pass,
tool #126 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: check_url_status
Old path: app/agents/tools.py (`_CHECK_URL_STATUS_TOOL` schema dict,
    `check_url_status_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/check_url_status.py (this file) —
    `CHECK_URL_STATUS_TOOL`, `check_url_status_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `check_url_status` in `allowed_tools` (plus interactive chat,
    newly — see finding #2).
Affected modules: app/agents/tools.py (`check_url_status_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "check_url_status" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_check_url_status_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/check_url_status.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **A genuine, live SSRF (server-side request forgery) — zero
   protection at all.** `check_url_status_h` passed the LLM-controlled
   `url` field straight to `urllib.request.urlopen()` with no
   validation whatsoever — unlike `fetch_url` (tool #88-era,
   `app/tools/execution/fetch_url.py`), which already gates every
   outbound fetch through the shared `_ssrf_denial_reason()` guard.
   Proved live: started a real local HTTP server on
   `127.0.0.1:18765` and confirmed `check_url_status_h` genuinely
   connected to it and returned a real `HTTP 200 OK` response — the
   same private/loopback address class `_ssrf_denial_reason()` already
   blocks for `fetch_url`. This tool could be used to probe internal
   services, port-scan the internal network, or reach a cloud
   metadata endpoint, learning live/dead + response-time information
   about hosts the calling agent has no business reaching.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/#110/#112/#118/#120/#122.**
   `check_url_status` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: check_url_status"`.

Fixed via a shared `check_url_status_handler()`: `url` is validated
with the same, already-proven-correct `_ssrf_denial_reason()` guard
`fetch_url` uses, before any network access — closing finding #1
using an established, reused mechanism rather than a new one. A new
`chat_agent.py` dispatch branch delegates to this same shared handler,
closing finding #2.
"""

from __future__ import annotations

import time
import urllib.request
from typing import Any

from app.agents.tool_security import _ssrf_denial_reason

CHECK_URL_STATUS_TOOL: dict[str, Any] = {
    "name": "check_url_status",
    "description": "Check the HTTP status code of a URL. Returns status code, redirect chain, and response time. Does NOT return body.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to check"}},
        "required": ["url"],
    },
}


def check_url_status_handler(inp: dict[str, Any]) -> str:
    """Core check_url_status logic — the one real implementation,
    reused unchanged in behavior except for the SSRF guard now applied
    to `url` before any network access."""
    url = str(inp["url"])
    ssrf_reason = _ssrf_denial_reason(url)
    if ssrf_reason:
        return f"[POLICY DENIED] {ssrf_reason}"

    try:
        start = time.time()
        r = urllib.request.urlopen(url, timeout=10)
        elapsed = round((time.time() - start) * 1000)
        return f"HTTP {r.status} {r.reason} ({elapsed}ms) — {url}"
    except Exception as e:
        return f"[ERROR] check_url_status {url}: {e}"
