"""web_search tool — tool_enhance.md productionization pass, tool #88
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: web_search
Old path: app/agents/tools.py — a single module-level `web_search()`
    function (NOT duplicated; both `make_research_handlers()` and
    `make_chat_handlers()` wire the exact same function object).
New path: app/tools/integrations/web_search.py (this file) —
    `WEB_SEARCH_TOOL`, `web_search_handler`.
Affected agents: per tool_inventory.json, 7 agents declare `web_search`
    in `allowed_tools`. Confirmed NOT in `CHAT_TOOLS` — intentional,
    the interactive chat session never gets unrestricted live web
    search; `app/agents/chat_agent.py` correctly has no dispatch
    branch for it.
Affected modules: app/agents/tools.py (both real call sites now import
    the shared handler rather than defining it locally).
Affected registries: `app/fleet/tool_manifest.py`'s "web_search" entry
    already declares `retry_policy="backoff"` (verified via
    `tests/test_stage4_tier3_tool_level_retry.py`) — unrelated to this
    file, unaffected by the move.
Affected tests: none required changes — every existing real test
    accesses this tool via `make_research_handlers()`/
    `make_chat_handlers()`'s `handlers["web_search"]`, or checks
    wiring/contract/manifest metadata rather than calling the real
    handler. New tests added: see tests/test_web_search_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/web_search.md.
---------------------------------------------------------------------------

No security vulnerability found. `query` is a plain search string
passed to the `duckduckgo_search` library's `DDGS().text()` call — no
subprocess, no shell, no file-path handling, so none of this
initiative's established finding classes (flag-collision, worktree
escape, shell injection) apply. `DDGS()`'s own default `timeout=10`
(verified via `inspect.signature`) already bounds the outbound HTTP
call — no unbounded-timeout risk, unlike tool #86's `fetch_url` before
its fix. `max_results=5` is a fixed literal, not LLM-controlled, so no
resource-exhaustion angle via requesting an enormous result count.
Already wrapped in a broad `try/except Exception`, so no
uncaught-exception class either. Real search-result CONTENT already
gets wrapped as untrusted data and scanned for prompt-injection markers
by a separate, pre-existing defense layer
(`tests/test_phase63_prompt_injection_defense.py`) — unrelated to this
tool's own code and left untouched.

**Out-of-scope observation, documented but not acted on**: the
installed `duckduckgo_search` PyPI package emits a real
`RuntimeWarning` at call time — it has been renamed to `ddgs` upstream.
This is a genuine future-maintenance risk (the old package name may
stop receiving updates), but changing a project dependency is outside
this security-hardening pass's scope and risks its own regression;
logged here for a future, deliberate dependency-upgrade decision
rather than folded into this turn.

Extracted verbatim (no behavior change) purely for modularization —
matches this initiative's mandatory per-tool modularization rule even
when no vulnerability was found (same precedent as tool #85's
`submit_docs`).
"""

from __future__ import annotations

from typing import Any

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for technical information using DuckDuckGo. "
        "Returns titles, URLs, and snippets for up to 5 results. "
        "Use for finding library documentation, versions, and best practices."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
}


def web_search_handler(inp: dict[str, Any]) -> str:
    """Search the web via DuckDuckGo — no API key needed. Standalone (not
    repo-scoped) so any agent can reuse it, not just the research agent."""
    query = str(inp.get("query", "")).strip()
    if not query:
        return "[ERROR] query is required"
    try:
        from duckduckgo_search import DDGS

        results = list(DDGS().text(query, max_results=5))
        if not results:
            return f"(no results found for: {query!r})"
        lines = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")[:300]
            lines.append(f"## {title}\n{href}\n{body}")
        return "\n\n".join(lines)[:6000]
    except Exception as exc:
        return f"[ERROR] web_search failed: {exc}"
