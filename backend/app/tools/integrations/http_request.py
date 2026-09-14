"""http_request tool — tool_enhance.md productionization pass, tool
#155 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: http_request
Old path: app/agents/tools.py (`_HTTP_REQUEST_TOOL` schema dict,
    `http_request_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/integrations/http_request.py (this file) —
    `HTTP_REQUEST_TOOL`, `http_request_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `http_request` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`http_request_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "http_request" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_http_request_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/http_request.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **A real SSRF vector, including local-file disclosure via the
   `file://` scheme.** `http_request_h` called `urlopen()` on `url`
   with ZERO SSRF/scheme validation — unlike its sibling outbound-
   fetch tools `fetch_url` and `check_url_status`, which already both
   use the shared `_ssrf_denial_reason()` guard
   (`app.agents.tool_security`, audit_v1.md 4.5/4.8's original
   `fetch_url` SSRF finding). Proved live (isolated, standalone
   `urllib.request` call mirroring the handler's exact code path, not
   assumed): `urlopen(Request("file:///etc/hostname", method="GET",
   headers={}))` genuinely read the real local file's content
   (`resp.read()` returned the real hostname bytes). The existing
   handler happened to then crash on `resp.reason` (a `file://`
   response object has no `.reason` attribute, unlike a real HTTP
   response), which currently prevents the already-read content from
   reaching the caller — but this is an accidental side effect of
   unrelated response-formatting code, not an intentional safeguard,
   and is fragile. Beyond `file://`, the tool was also fully exposed
   to internal-network SSRF (cloud metadata endpoint
   `169.254.169.254`, localhost admin ports, RFC1918 ranges) with no
   protection at all — the exact same class already fixed for
   `fetch_url`/`check_url_status`.

2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154.**
   `http_request` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: http_request"`.

UPDATE (2026-09-14, tool #157's audit): the `_ssrf_denial_reason()`
guard added below only validates the caller-supplied `url` — a real
SSRF-via-redirect bypass was discovered while auditing sibling tool
#157 (`inspect_openapi_spec`): `urlopen()` follows HTTP redirects by
default with NO re-validation of the redirect target, so a malicious
or compromised external server the initial URL legitimately points
to could redirect the request to a private/internal target (proved
live against the real cloud metadata endpoint via a real public
redirect service). Now closed too, via `_ssrf_safe_opener()`
(`app.agents.tool_security` — see that module's own docstring for the
full cross-cutting account, which also affected `fetch_url`/
`check_url_status`).

Fixed via a shared `http_request_handler()`: `url` is now validated
with the same, already-proven-correct `_ssrf_denial_reason()` guard
`fetch_url`/`check_url_status` already use (direct import, not
dependency-injection, matching `check_url_status.py`'s own precedent
— `_ssrf_denial_reason` is broadly shared, not tool-specific), closing
finding #1 definitively (rejects non-http(s) schemes, including
`file://`, AND resolves the hostname to deny private/loopback/
link-local/reserved-range destinations, AND — per the update above —
every subsequent redirect hop too). A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing
finding #2.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from app.agents.tool_security import _ssrf_denial_reason, _ssrf_safe_opener

HTTP_REQUEST_TOOL: dict[str, Any] = {
    "name": "http_request",
    "description": "Make an HTTP request (GET/POST/PUT/DELETE) with custom headers and body. Returns status code and response body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
            "url": {"type": "string", "description": "Request URL"},
            "headers": {
                "type": "object",
                "description": "Request headers (key-value pairs)",
            },
            "body": {
                "type": "string",
                "description": "Request body (JSON string for POST/PUT)",
            },
        },
        "required": ["method", "url"],
    },
}


def http_request_handler(inp: dict[str, Any]) -> str:
    """Core http_request logic — the one real implementation, reused
    unchanged in behavior except for the SSRF guard now applied to
    `url` before any network access, and every subsequent redirect hop
    now also re-validated via `_ssrf_safe_opener()` (tool #157's
    cross-cutting SSRF-via-redirect fix — see tool_security.py's own
    module docstring)."""
    method = str(inp["method"]).upper()
    url = str(inp["url"])
    ssrf_reason = _ssrf_denial_reason(url)
    if ssrf_reason:
        return f"[POLICY DENIED] {ssrf_reason}"

    headers = dict(inp.get("headers") or {})
    body = inp.get("body")
    try:
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with _ssrf_safe_opener().open(req, timeout=15) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")[:3000]
            return f"HTTP {resp.status} {resp.reason}\n{text}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return f"[ERROR] http_request: {e}"
