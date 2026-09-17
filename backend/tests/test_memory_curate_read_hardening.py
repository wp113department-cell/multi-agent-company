"""memory_curate_read tool #223 — tool_enhance.md productionization
pass (2026-09-17).

Two real findings:

1. Same "uncaught crash on malformed numeric input" class already
   found and fixed on tools #215/#216/#218: `limit = int(inp.get(
   "limit", 20))` happened BEFORE the function's own try/except, so a
   malformed limit raised an uncaught ValueError. Proved live:
   memory_curate_read({"limit": "not-a-number"}) raised straight out
   of the handler. Fixed by moving the coercion inside the guard.

2. Same "local duplicate isolated-engine helper" finding already
   documented and fixed tool-by-tool starting with tool #212's
   submit_enhancement_request: this handler used the local
   _new_isolated_db_engine() instead of the canonical
   app.db.session.new_isolated_async_engine(). Fixed for this tool
   specifically.

No SQL injection surface: `category` only ever reaches a parametrized
SQLAlchemy ORM .where(...) comparison.
"""

from __future__ import annotations

import inspect

from app.agents.tools import CHAT_TOOLS, memory_curate_read
from app.tools.agents.memory_curate_read import (
    MEMORY_CURATE_READ_TOOL,
    memory_curate_read_handler,
)


def test_schema() -> None:
    assert MEMORY_CURATE_READ_TOOL["name"] == "memory_curate_read"
    props = MEMORY_CURATE_READ_TOOL["input_schema"]["properties"]  # type: ignore[index]
    assert "category" in props
    assert "limit" in props


def test_not_in_chat_tools() -> None:
    assert "memory_curate_read" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: malformed `limit` no longer crashes
# ---------------------------------------------------------------------------


def test_malformed_limit_string_returns_clean_error_not_uncaught_exception() -> None:
    result = memory_curate_read_handler({"limit": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "memory_curate_read" in result


def test_malformed_limit_none_type_returns_clean_error() -> None:
    result = memory_curate_read_handler({"limit": None})
    assert result.startswith("[ERROR]")


def test_malformed_limit_list_type_returns_clean_error() -> None:
    result = memory_curate_read_handler({"limit": [1, 2, 3]})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# The real finding: canonical isolated-engine helper, not the local duplicate
# ---------------------------------------------------------------------------


def test_uses_the_canonical_isolated_engine_helper_not_the_local_duplicate() -> None:
    source = inspect.getsource(memory_curate_read_handler)
    assert "new_isolated_async_engine" in source
    assert "_new_isolated_db_engine" not in source


# ---------------------------------------------------------------------------
# Legitimate-usage regression (real DB, matches this project's own
# established convention of testing against the live dev Postgres)
# ---------------------------------------------------------------------------


def test_real_db_read_returns_a_string_without_crashing() -> None:
    result = memory_curate_read_handler({})
    assert isinstance(result, str)
    assert result != ""


def test_real_db_read_with_category_filter_and_explicit_limit() -> None:
    result = memory_curate_read_handler({"category": "task", "limit": 5})
    assert isinstance(result, str)


def test_nonexistent_category_returns_clean_no_entries_message_or_data() -> None:
    result = memory_curate_read_handler(
        {"category": "definitely-not-a-real-category-xyz"}
    )
    assert isinstance(result, str)
    assert not result.startswith("Traceback")


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _MEMORY_CURATE_READ_TOOL

    assert memory_curate_read is memory_curate_read_handler
    assert _MEMORY_CURATE_READ_TOOL is MEMORY_CURATE_READ_TOOL


def test_knowledge_curator_imports_the_shared_handler() -> None:
    from app.agents import knowledge_curator as mod

    assert mod.memory_curate_read is memory_curate_read_handler
