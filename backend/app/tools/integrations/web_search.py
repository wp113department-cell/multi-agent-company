"""web_search tool — searches the web through Firecrawl.

2026-10-14 (owner decision): replaces the DuckDuckGo scraping search. The
`duckduckgo_search` package was renamed upstream and returned no results
at all; its successor `ddgs` worked but search sites rate-limited it after
a handful of queries. Firecrawl is an API with a key (FIRECRAWL_API_KEY),
so results are reliable and usage is metered by the owner's account.

Used by the research, spike, tech advisor, prompt engineer, MCP developer,
agentic AI architect, agent performance reviewer and bhaskar agents; the
chat is not given web search. `query` is a plain string sent to the API (no
shell, no file paths); results are capped at 5 and 6,000 characters, and
the agent loop wraps the text as untrusted content and scans it for
prompt-injection markers. The API key never appears in a result.
"""

from __future__ import annotations

from typing import Any

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for technical information. "
        "Returns titles, URLs, and descriptions for up to 5 results. "
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

_MAX_RESULTS = 5
_TIMEOUT_MS = 30_000


def web_search_handler(inp: dict[str, Any]) -> str:
    """Search the web through Firecrawl (2026-10-14, owner decision: replaces
    the scraping-based DuckDuckGo search, which returned nothing once the
    library was renamed and was rate-limited when it worked). Needs
    FIRECRAWL_API_KEY. Standalone (not repo-scoped) so any agent can reuse
    it. Result text is treated as untrusted content by the agent loop."""
    query = str(inp.get("query", "")).strip()
    if not query:
        return "[ERROR] query is required"
    from app.config import get_settings

    api_key = get_settings().firecrawl_api_key
    if not api_key:
        return (
            "[ERROR] web search is not set up: set FIRECRAWL_API_KEY "
            "(see backend/.env.example)"
        )
    try:
        from firecrawl import Firecrawl

        results = Firecrawl(api_key=api_key).search(
            query, limit=_MAX_RESULTS, timeout=_TIMEOUT_MS
        )
        web = list(getattr(results, "web", None) or [])
        if not web:
            return f"(no results found for: {query!r})"
        lines = []
        for r in web:
            title = getattr(r, "title", None) or "No title"
            url = getattr(r, "url", None) or ""
            description = (getattr(r, "description", None) or "")[:300]
            lines.append(f"## {title}\n{url}\n{description}")
        return "\n\n".join(lines)[:6000]
    except Exception as exc:
        # never echo the key back into an agent's context
        return f"[ERROR] web_search failed: {str(exc).replace(api_key, '***')}"
