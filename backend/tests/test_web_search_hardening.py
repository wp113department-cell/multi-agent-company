"""web_search tool #88 — tool_enhance.md productionization pass
(2026-08-24).

No security vulnerability found. Single implementation (not
duplicated — `make_research_handlers()` and `make_chat_handlers()`
both wire the exact same function object), extracted verbatim into
`app.tools.integrations.web_search` purely for modularization. `query`
is a plain search string with no subprocess/shell/path-handling
surface; `DDGS()`'s own default `timeout=10` already bounds the
outbound HTTP call; `max_results=5` is a fixed literal, not
LLM-controlled; already wrapped in a broad `try/except Exception`.

Confirmed NOT in `CHAT_TOOLS` — intentional, the interactive chat
session never gets unrestricted live web search.

Real search-result CONTENT already gets wrapped as untrusted data and
scanned for prompt-injection markers by a separate, pre-existing
defense layer (`test_phase63_prompt_injection_defense.py`) — unrelated
to this tool's own code, not re-tested here.

Tests here that reach the network use a real, common query — matching
this test suite's own established pattern of hitting real external
services rather than mocking them entirely (see tool #86's
`test_fetch_url_hardening.py`).
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    RESEARCH_TOOLS,
    make_chat_handlers,
    make_research_handlers,
)
from app.tools.integrations.web_search import WEB_SEARCH_TOOL, web_search_handler


def test_web_search_tool_schema_requires_query() -> None:
    assert WEB_SEARCH_TOOL["name"] == "web_search"
    assert WEB_SEARCH_TOOL["input_schema"]["required"] == ["query"]  # type: ignore[index]


def test_web_search_is_not_in_chat_tools() -> None:
    """Intentional — the interactive session never gets unrestricted
    live web search."""
    names = [t["name"] for t in CHAT_TOOLS]
    assert "web_search" not in names


def test_web_search_appears_exactly_once_in_research_tools() -> None:
    names = [t["name"] for t in RESEARCH_TOOLS]
    assert names.count("web_search") == 1


def test_web_search_handler_rejects_empty_query() -> None:
    assert web_search_handler({"query": ""}) == "[ERROR] query is required"


def test_web_search_handler_rejects_whitespace_only_query() -> None:
    assert web_search_handler({"query": "   "}) == "[ERROR] query is required"


def test_web_search_handler_rejects_missing_query() -> None:
    assert web_search_handler({}) == "[ERROR] query is required"


def test_web_search_handler_handles_library_exceptions_gracefully(monkeypatch) -> None:
    """Real, exercised path: if the underlying library raises for any
    reason (network down, blocked, rate-limited), the handler must not
    propagate an uncaught exception."""
    import app.tools.integrations.web_search as web_search_module

    class _BoomDDGS:
        def text(self, *args, **kwargs):
            raise RuntimeError("simulated network failure")

    import duckduckgo_search

    monkeypatch.setattr(duckduckgo_search, "DDGS", lambda: _BoomDDGS())
    result = web_search_module.web_search_handler({"query": "anything"})
    assert result.startswith("[ERROR] web_search failed:")


def test_web_search_handler_truncates_long_output(monkeypatch) -> None:
    import app.tools.integrations.web_search as web_search_module

    class _HugeDDGS:
        def text(self, *args, **kwargs):
            return [
                {
                    "title": f"T{i}",
                    "href": f"https://example.com/{i}",
                    "body": "x" * 500,
                }
                for i in range(5)
            ]

    import duckduckgo_search

    monkeypatch.setattr(duckduckgo_search, "DDGS", lambda: _HugeDDGS())
    result = web_search_module.web_search_handler({"query": "anything"})
    assert len(result) <= 6000


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths (a real, live network search)
# ---------------------------------------------------------------------------


def test_make_research_handlers_real_search_returns_real_results() -> None:
    handlers = make_research_handlers(".")
    result = handlers["web_search"]({"query": "python programming"})
    assert "[ERROR]" not in result
    assert "python" in result.lower() or "Python" in result


def test_make_chat_handlers_real_search_returns_real_results() -> None:
    handlers = make_chat_handlers(".")
    result = handlers["web_search"]({"query": "python programming"})
    assert "[ERROR]" not in result
    assert "python" in result.lower() or "Python" in result
