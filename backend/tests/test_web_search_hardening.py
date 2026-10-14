"""web_search tool — Firecrawl (2026-10-14, owner decision).

Replaces the DuckDuckGo scraping search: `duckduckgo_search` (renamed
upstream) returned no results at all, and its successor `ddgs` was
rate-limited by the search sites after a few queries. Firecrawl is a keyed
API (FIRECRAWL_API_KEY).

These tests use a fake Firecrawl client: CI has no key and a real search
spends the owner's credits. The real service was checked once by hand on
2026-10-14 (5 results, official LangGraph docs first).

Confirmed NOT in `CHAT_TOOLS` — intentional, the interactive chat session
never gets live web search. Result content is wrapped as untrusted data and
scanned for prompt-injection markers by the agent loop
(`test_phase63_prompt_injection_defense.py`), not re-tested here.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.tools import (
    CHAT_TOOLS,
    RESEARCH_TOOLS,
    make_chat_handlers,
    make_research_handlers,
)
from app.config import get_settings
from app.tools.integrations.web_search import WEB_SEARCH_TOOL, web_search_handler

KEY = "fc-test-key-not-real"


class _FakeFirecrawl:
    calls: list[dict[str, Any]] = []
    web: list[Any] = []
    error: Exception | None = None

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, **kw: Any) -> Any:
        _FakeFirecrawl.calls.append({"query": query, "api_key": self.api_key, **kw})
        if _FakeFirecrawl.error:
            raise _FakeFirecrawl.error
        return SimpleNamespace(web=_FakeFirecrawl.web)


def _hit(i: int, description: str = "about it") -> Any:
    return SimpleNamespace(
        title=f"Result {i}", url=f"https://example.com/{i}", description=description
    )


@pytest.fixture
def firecrawl(monkeypatch: pytest.MonkeyPatch) -> type[_FakeFirecrawl]:
    import firecrawl as firecrawl_pkg

    _FakeFirecrawl.calls = []
    _FakeFirecrawl.web = [_hit(1), _hit(2)]
    _FakeFirecrawl.error = None
    monkeypatch.setattr(firecrawl_pkg, "Firecrawl", _FakeFirecrawl)
    monkeypatch.setattr(get_settings(), "firecrawl_api_key", KEY)
    return _FakeFirecrawl


def test_web_search_tool_schema_requires_query() -> None:
    assert WEB_SEARCH_TOOL["name"] == "web_search"
    assert WEB_SEARCH_TOOL["input_schema"]["required"] == ["query"]  # type: ignore[index]


def test_web_search_is_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "web_search" not in names


def test_web_search_appears_exactly_once_in_research_tools() -> None:
    names = [t["name"] for t in RESEARCH_TOOLS]
    assert names.count("web_search") == 1


@pytest.mark.parametrize("inp", [{"query": ""}, {"query": "   "}, {}])
def test_an_empty_query_is_refused(inp: dict[str, Any]) -> None:
    assert web_search_handler(inp) == "[ERROR] query is required"


def test_without_a_key_it_says_web_search_is_not_set_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "firecrawl_api_key", "")
    result = web_search_handler({"query": "langgraph"})
    assert result.startswith("[ERROR] web search is not set up")


def test_results_are_titles_urls_and_descriptions(firecrawl: Any) -> None:
    result = web_search_handler({"query": "langgraph docs"})
    assert "## Result 1\nhttps://example.com/1\nabout it" in result
    [call] = firecrawl.calls
    assert call["query"] == "langgraph docs" and call["limit"] == 5
    assert call["api_key"] == KEY


def test_no_results_is_reported_honestly(firecrawl: Any) -> None:
    firecrawl.web = []
    assert web_search_handler({"query": "zzz"}) == "(no results found for: 'zzz')"


def test_a_failure_never_raises_and_never_leaks_the_key(firecrawl: Any) -> None:
    firecrawl.error = RuntimeError(f"401 Unauthorized for key {KEY}")
    result = web_search_handler({"query": "anything"})
    assert result.startswith("[ERROR] web_search failed:")
    assert KEY not in result


def test_long_output_is_capped(firecrawl: Any) -> None:
    firecrawl.web = [_hit(i, "x" * 2000) for i in range(5)]
    assert len(web_search_handler({"query": "anything"})) <= 6000


def test_both_agent_handler_sets_use_it(firecrawl: Any) -> None:
    for handlers in (make_research_handlers("."), make_chat_handlers(".")):
        assert "Result 1" in handlers["web_search"]({"query": "python"})
