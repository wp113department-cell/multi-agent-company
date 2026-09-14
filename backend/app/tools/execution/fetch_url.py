"""fetch_url tool — tool_enhance.md productionization pass, tool #86
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: fetch_url
Old path: app/agents/tools.py (`_FETCH_URL_TOOL` schema dict) with
    THREE real implementations: `ae_fetch_url` (inside
    `make_ai_engineer_handlers()` — narrower, `urllib.request`-based,
    silently ignores the schema's own `timeout`/`summarize` fields),
    the general `fetch_url` closure inside `make_chat_handlers()`
    (~35 one-shot agents, curl-subprocess-based), and
    `app/agents/chat_agent.py`'s separate interactive dispatch (also
    curl-based, via a shell string).
New path: app/tools/execution/fetch_url.py (this file) —
    `FETCH_URL_TOOL`, `fetch_url_handler`. ALL THREE real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 7 agents declare `fetch_url`
    in `allowed_tools`.
Affected modules: app/agents/tools.py (its own `fetch_url` and
    `ae_fetch_url` closures delegate to the shared handler),
    app/agents/chat_agent.py (its dispatch now calls the same shared
    handler). `_llm_summarize_url_content` (an LLM-calling helper that
    lives in `app.agents.tools`) is imported with a deferred
    (function-body) import to avoid a circular import — `app.agents.
    tools` imports this module at module load time, so a module-level
    import back the other way would fail.
Affected registries: none — app/fleet/tool_manifest.py's "fetch_url"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_fetch_url_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/fetch_url.md.
---------------------------------------------------------------------------

SSRF protection was already correct and unchanged — `_ssrf_denial_
reason()` (`app.agents.tool_security`) resolves the hostname and
rejects any private/loopback/link-local/reserved address, including
the cloud-metadata endpoint `169.254.169.254`, checking the RESOLVED
IP (not just the hostname string) so DNS-rebinding/bare-IP URLs are
caught too. Re-verified live on all three real call sites — no fix
needed, no regression introduced.

Two real, empirically-verified findings, both flagged as pending back
in tool #14's own audit ("3 known unbounded-timeout findings now on
the books... `fetch_url`'s timeout") and now closed for real.

1. **An unbounded, LLM-controlled `timeout`, on TWO of the three real
   implementations** (`make_chat_handlers()`'s closure and
   `chat_agent.py`'s dispatch — `ae_fetch_url` hardcodes 10s and never
   reads the field at all, so it was never exposed to this). Neither
   clamped the upper bound before passing it to both curl's own
   `--max-time` flag and the wrapping `subprocess.run(..., timeout=
   fu_timeout + 5)` — a real resource-exhaustion vector, the same
   pattern already fixed for `run_python_snippet` in tool #14.

2. **An uncaught `ValueError` on a non-numeric `timeout`, on the same
   two implementations** — same class as tool #78's `git_log`. Proved
   live: `fetch_url({"url": "http://example.com", "timeout":
   "not_a_number"})` raised `ValueError: invalid literal for int()
   with base 10: 'not_a_number'` uncaught through both real dispatch
   paths.

A secondary, non-security finding: `ae_fetch_url` (the `ai_engineer`
agent's implementation) silently ignores its own advertised
`timeout`/`summarize` schema fields — always fetches with a hardcoded
10s timeout via `urllib.request` and never generates a summary even
when `summarize=true` is passed, a real functionality-parity gap the
LLM has no way to detect from the tool's own description.

Fixed via a shared `fetch_url_handler()`, adopted by all three real
call sites: `timeout`'s conversion is wrapped in
`try/except (TypeError, ValueError)`, returning a clean `[ERROR]
timeout must be an integer, got ...` message (closes finding #2); the
result is then clamped to `[1, MAX_FETCH_URL_TIMEOUT_SECONDS]` (closes
finding #1); `ae_fetch_url` is upgraded onto the same curl-based
implementation the other two already used (matching its own advertised
schema for the first time, closing the secondary finding) rather than
keeping its narrower `urllib.request` path.
"""

from __future__ import annotations

import subprocess
from typing import Any

from app.agents.tool_security import _ssrf_denial_reason, _ssrf_safe_curl_fetch

MAX_FETCH_URL_TIMEOUT_SECONDS = 60

FETCH_URL_TOOL = {
    "name": "fetch_url",
    "description": "Fetch content from a URL (HTTP GET). Useful for reading documentation or checking API endpoints. Set summarize=true to also get an LLM-generated summary of the fetched content ahead of the raw text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 15)",
            },
            "summarize": {
                "type": "boolean",
                "description": "If true, prepend an LLM-generated summary of the fetched content (default: false)",
            },
        },
        "required": ["url"],
    },
}


def fetch_url_handler(inp: dict[str, Any]) -> str:
    """Core fetch_url logic shared by all three real call sites."""
    url = str(inp["url"])
    ssrf_reason = _ssrf_denial_reason(url)
    if ssrf_reason:
        return f"[POLICY DENIED] {ssrf_reason}"

    try:
        timeout = int(inp.get("timeout", 15))
    except (TypeError, ValueError):
        return f"[ERROR] timeout must be an integer, got {inp.get('timeout')!r}"
    timeout = max(1, min(timeout, MAX_FETCH_URL_TIMEOUT_SECONDS))

    summarize = bool(inp.get("summarize", False))

    try:
        # tool_enhance.md productionization pass, tool #157 (2026-09-14)
        # — was a real SSRF-via-redirect bypass: the _ssrf_denial_reason()
        # check above only validated this initial `url`; curl's own `-L`
        # auto-redirect-following let a malicious/compromised server this
        # URL legitimately points to redirect the request to a private/
        # internal target, completely unvalidated (proved live against
        # the real cloud metadata endpoint via a real public redirect
        # service). Now fetches via _ssrf_safe_curl_fetch(), which
        # re-validates every redirect hop the same way instead of using
        # curl's own -L. See tool_security.py's own module docstring for
        # the full cross-cutting account.
        raw, denial_reason = _ssrf_safe_curl_fetch(url, timeout=timeout)
        if denial_reason:
            return f"[POLICY DENIED] {denial_reason}"
        if summarize and raw and raw != "[empty response]":
            from app.agents.tools import _llm_summarize_url_content

            summary = _llm_summarize_url_content(url, raw)
            if summary:
                return f"=== Summary ===\n{summary}\n\n=== Raw content ===\n{raw}"
        return raw
    except subprocess.TimeoutExpired:
        return f"[ERROR] Request timed out after {timeout}s"
    except FileNotFoundError:
        return "[ERROR] curl not found"
    except Exception as e:
        return f"[ERROR] {e}"
