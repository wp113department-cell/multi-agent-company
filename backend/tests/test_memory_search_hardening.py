"""memory_search tool #227 — tool_enhance.md productionization pass
(2026-09-17).

Two real findings, the same class already found and fixed on the rest
of this memory-tool family (memory_curate_read #223,
memory_curate_write #224, memory_list_draft_lessons #225):

1. TWO separate uncaught-crash paths, both happening before the
   function's own try/except: `top_k = int(inp.get("top_k", 5))` and
   `repo_id = int(repo_id_raw) if repo_id_raw is not None else None`.
   Proved live: both a malformed top_k and a malformed repo_id raised
   an uncaught ValueError. Fixed by moving both inside the guard.

2. Used the local _new_isolated_db_engine() instead of the canonical
   app.db.session.new_isolated_async_engine(). Fixed for this tool
   specifically — this is the last of the 4 memory tools flagged as
   using the local duplicate; the now-fully-dead local helper was
   removed from app.agents.tools entirely as part of this turn.

This tool already has thorough real-DB test coverage in
tests/test_cluster_o_phase1d_memory_search_tool.py (schema, cross-repo
leak-proofing, fleet-wide default, required-query regression) — none
of those 4 tests exercised a malformed top_k or repo_id.
"""

from __future__ import annotations

import inspect

from app.agents.tools import CHAT_TOOLS, memory_search
from app.tools.agents.memory_search import MEMORY_SEARCH_TOOL, memory_search_handler


def test_schema() -> None:
    assert MEMORY_SEARCH_TOOL["name"] == "memory_search"
    assert MEMORY_SEARCH_TOOL["input_schema"]["required"] == ["query"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "memory_search" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: malformed top_k/repo_id no longer crash
# ---------------------------------------------------------------------------


def test_malformed_top_k_string_returns_clean_error_not_uncaught_exception() -> None:
    result = memory_search_handler({"query": "x", "top_k": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "memory_search" in result


def test_malformed_repo_id_string_returns_clean_error() -> None:
    result = memory_search_handler({"query": "x", "repo_id": "not-a-number"})
    assert result.startswith("[ERROR]")


def test_malformed_top_k_list_returns_clean_error() -> None:
    result = memory_search_handler({"query": "x", "top_k": [1, 2]})
    assert result.startswith("[ERROR]")


def test_missing_query_still_returns_clean_error_without_network_call() -> None:
    assert memory_search_handler({}) == "[ERROR] query is required"


# ---------------------------------------------------------------------------
# The real finding: canonical isolated-engine helper, not the local duplicate
# ---------------------------------------------------------------------------


def test_uses_the_canonical_isolated_engine_helper_not_the_local_duplicate() -> None:
    source = inspect.getsource(memory_search_handler)
    assert "new_isolated_async_engine" in source
    assert "_new_isolated_db_engine" not in source


def test_local_duplicate_helper_no_longer_exists_in_tools_module() -> None:
    """The full memory-tool family (#223-#227) has now migrated off
    the local duplicate — confirms it was actually deleted, not just
    unreferenced by this one tool."""
    import app.agents.tools as tools_mod

    assert not hasattr(tools_mod, "_new_isolated_db_engine")


# ---------------------------------------------------------------------------
# Legitimate-usage regression (real DB, matches this project's own
# established convention of testing against the live dev Postgres)
# ---------------------------------------------------------------------------


def test_real_query_returns_a_string_without_crashing() -> None:
    result = memory_search_handler({"query": "a query unlikely to match anything real"})
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _MEMORY_SEARCH_TOOL

    assert memory_search is memory_search_handler
    assert _MEMORY_SEARCH_TOOL is MEMORY_SEARCH_TOOL


def test_knowledge_curator_imports_the_shared_handler() -> None:
    from app.agents import knowledge_curator as mod

    assert mod.memory_search is memory_search_handler
