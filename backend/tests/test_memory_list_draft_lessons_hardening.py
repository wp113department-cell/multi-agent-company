"""memory_list_draft_lessons tool #225 — tool_enhance.md
productionization pass (2026-09-17).

Two real findings, the exact same class already found and fixed on
sibling tool #223 (memory_curate_read):

1. `limit = int(inp.get("limit", 20))` happened before the function's
   own try/except. Proved live:
   memory_list_draft_lessons({"limit": "not-a-number"}) raised an
   uncaught ValueError. Fixed by moving the coercion inside the guard.

2. Used the local _new_isolated_db_engine() instead of the canonical
   app.db.session.new_isolated_async_engine(). Fixed for this tool
   specifically.

Existing tests (test_phase_gap6_memory_promote_lesson.py) only
exercised wiring/registration, never the handler's actual behavior
with real or malformed input — this file closes that gap.
"""

from __future__ import annotations

import inspect

from app.agents.tools import CHAT_TOOLS, memory_list_draft_lessons
from app.tools.agents.memory_list_draft_lessons import (
    MEMORY_LIST_DRAFT_LESSONS_TOOL,
    memory_list_draft_lessons_handler,
)


def test_schema() -> None:
    assert MEMORY_LIST_DRAFT_LESSONS_TOOL["name"] == "memory_list_draft_lessons"
    props = MEMORY_LIST_DRAFT_LESSONS_TOOL["input_schema"]["properties"]  # type: ignore[index]
    assert "limit" in props


def test_not_in_chat_tools() -> None:
    assert "memory_list_draft_lessons" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: malformed `limit` no longer crashes
# ---------------------------------------------------------------------------


def test_malformed_limit_string_returns_clean_error_not_uncaught_exception() -> None:
    result = memory_list_draft_lessons_handler({"limit": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "memory_list_draft_lessons" in result


def test_malformed_limit_none_type_returns_clean_error() -> None:
    result = memory_list_draft_lessons_handler({"limit": None})
    assert result.startswith("[ERROR]")


def test_malformed_limit_list_type_returns_clean_error() -> None:
    result = memory_list_draft_lessons_handler({"limit": [1, 2, 3]})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# The real finding: canonical isolated-engine helper, not the local duplicate
# ---------------------------------------------------------------------------


def test_uses_the_canonical_isolated_engine_helper_not_the_local_duplicate() -> None:
    source = inspect.getsource(memory_list_draft_lessons_handler)
    assert "new_isolated_async_engine" in source
    assert "_new_isolated_db_engine" not in source


# ---------------------------------------------------------------------------
# Legitimate-usage regression (real DB, matches this project's own
# established convention of testing against the live dev Postgres)
# ---------------------------------------------------------------------------


def test_real_db_read_returns_a_string_without_crashing() -> None:
    result = memory_list_draft_lessons_handler({})
    assert isinstance(result, str)
    assert result != ""


def test_real_db_read_with_explicit_limit() -> None:
    result = memory_list_draft_lessons_handler({"limit": 5})
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _MEMORY_LIST_DRAFT_LESSONS_TOOL

    assert memory_list_draft_lessons is memory_list_draft_lessons_handler
    assert _MEMORY_LIST_DRAFT_LESSONS_TOOL is MEMORY_LIST_DRAFT_LESSONS_TOOL


def test_knowledge_curator_imports_the_shared_handler() -> None:
    from app.agents import knowledge_curator as mod

    assert mod.memory_list_draft_lessons is memory_list_draft_lessons_handler
