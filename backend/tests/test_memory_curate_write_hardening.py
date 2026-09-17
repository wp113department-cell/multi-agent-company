"""memory_curate_write tool #224 — tool_enhance.md productionization
pass (2026-09-17).

Two real findings, worse than sibling tool #223's
(memory_curate_read) equivalent findings:

1. `row_id = int(inp["id"])` used bare dict indexing (not even
   `.get()`) AND happened before the function's own try/except.
   Proved live: a genuinely missing `id` key raised an uncaught
   KeyError, and a malformed `id` value raised an uncaught ValueError
   — two separate uncaught-crash paths. Fixed by moving the coercion
   inside the guard and using `.get("id")` for a clean error message.

2. Same local-duplicate-isolated-engine-helper finding first
   documented on tool #212's submit_enhancement_request, most
   recently on tool #223's memory_curate_read: used
   _new_isolated_db_engine() instead of the canonical
   app.db.session.new_isolated_async_engine(). Fixed for this tool
   specifically.
"""

from __future__ import annotations

import asyncio
import inspect

from app.agents.tools import CHAT_TOOLS, memory_curate_write
from app.tools.agents.memory_curate_write import (
    MEMORY_CURATE_WRITE_TOOL,
    memory_curate_write_handler,
)


def test_schema() -> None:
    assert MEMORY_CURATE_WRITE_TOOL["name"] == "memory_curate_write"
    assert MEMORY_CURATE_WRITE_TOOL["input_schema"]["required"] == ["id"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "memory_curate_write" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real findings: missing/malformed `id` no longer crashes
# ---------------------------------------------------------------------------


def test_missing_id_key_returns_clean_error_not_uncaught_keyerror() -> None:
    result = memory_curate_write_handler({"note": "test"})
    assert result == "[ERROR] id is required"


def test_malformed_id_string_returns_clean_error_not_uncaught_valueerror() -> None:
    result = memory_curate_write_handler({"id": "not-a-number", "note": "test"})
    assert result.startswith("[ERROR]")
    assert "memory_curate_write" in result


def test_malformed_id_none_returns_clean_error() -> None:
    result = memory_curate_write_handler({"id": None, "note": "test"})
    assert result.startswith("[ERROR]")


def test_malformed_id_list_returns_clean_error() -> None:
    result = memory_curate_write_handler({"id": [1, 2], "note": "test"})
    assert result.startswith("[ERROR]")


def test_no_category_or_note_returns_nothing_to_update_error() -> None:
    result = memory_curate_write_handler({"id": 1})
    assert result == "[ERROR] provide category and/or note — nothing to update"


def test_nonexistent_id_still_returns_clean_not_found_error() -> None:
    result = memory_curate_write_handler({"id": 999999999, "note": "x"})
    assert result == "[ERROR] No memory entry with id=999999999"


# ---------------------------------------------------------------------------
# The real finding: canonical isolated-engine helper, not the local duplicate
# ---------------------------------------------------------------------------


def test_uses_the_canonical_isolated_engine_helper_not_the_local_duplicate() -> None:
    source = inspect.getsource(memory_curate_write_handler)
    assert "new_isolated_async_engine" in source
    assert "_new_isolated_db_engine" not in source


# ---------------------------------------------------------------------------
# Legitimate-usage regression (real DB, matches this project's own
# established convention of testing against the live dev Postgres)
# ---------------------------------------------------------------------------


def test_real_write_updates_a_real_row() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import MemoryEmbedding
    from app.db.session import new_isolated_async_engine

    async def _create() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = MemoryEmbedding(
                    task_id="t-hardening-224",
                    outcome="completed",
                    category="task",
                    description="d",
                    summary="original summary",
                    files_changed=[],
                )
                session.add(row)
                await session.commit()
                return row.id
        finally:
            await engine.dispose()

    row_id = asyncio.run(_create())
    result = memory_curate_write_handler({"id": row_id, "note": "hardening probe"})
    assert result == f"Memory entry #{row_id} updated."


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _MEMORY_CURATE_WRITE_TOOL

    assert memory_curate_write is memory_curate_write_handler
    assert _MEMORY_CURATE_WRITE_TOOL is MEMORY_CURATE_WRITE_TOOL


def test_knowledge_curator_imports_the_shared_handler() -> None:
    from app.agents import knowledge_curator as mod

    assert mod.memory_curate_write is memory_curate_write_handler
