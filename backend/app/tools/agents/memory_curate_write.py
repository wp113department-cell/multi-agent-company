"""memory_curate_write tool — tool_enhance.md productionization pass,
tool #224 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_curate_write
Old path: app/agents/tools.py (`_MEMORY_CURATE_WRITE_TOOL` schema
    dict, module-level `memory_curate_write()` function).
New path: app/tools/agents/memory_curate_write.py (this file) —
    `MEMORY_CURATE_WRITE_TOOL`, `memory_curate_write_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `knowledge_curator` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import memory_curate_write` unchanged.
Affected tests: `tests/test_day9_fleet_agents.py`'s
    `test_memory_curate_write_updates_row` and
    `test_memory_curate_write_missing_id` already exercise this tool
    against the real dev Postgres database — re-run and confirmed
    passing unchanged. Note: despite its name,
    `test_memory_curate_write_missing_id` actually passes a
    NONEXISTENT id (999999999), not a genuinely missing `id` key — the
    real "id key absent from input entirely" case was never covered.
    New tests added: see tests/test_memory_curate_write_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_curate_write.md.
---------------------------------------------------------------------------

Two real findings, worse than the sibling tool #223's
(`memory_curate_read`) equivalent findings:

1. `row_id = int(inp["id"])` used BARE DICT INDEXING (`inp["id"]`, not
   even `.get()`) AND happened before the function's own
   `try: found = asyncio.run(_update()) except Exception: return
   "[ERROR] ..."` block. Proved live, before any fix: a genuinely
   missing `id` key raised an uncaught `KeyError`, and a malformed
   `id` value (e.g. `"not-a-number"`) raised an uncaught `ValueError`
   — TWO separate uncaught-crash paths, not just one. Fixed by moving
   the coercion inside the guard and using `.get("id")` so a missing
   key produces a clean, specific `"[ERROR] id is required"` message
   rather than a raw `KeyError`.

2. Same "local duplicate isolated-engine helper" finding already
   documented and fixed tool-by-tool starting with tool #212's
   `submit_enhancement_request`, most recently on tool #223's sibling
   `memory_curate_read`: used the local, less-completely-configured
   `_new_isolated_db_engine()` instead of the canonical
   `app.db.session.new_isolated_async_engine()`. Fixed for this tool
   specifically — 2 other tools (`memory_search`,
   `memory_list_draft_lessons`) still use the local duplicate as of
   this turn, deliberately left for their own future turns.

No SQL injection surface: `row_id` is coerced to `int` before ever
reaching `session.get(MemoryEmbedding, row_id)` (a parametrized ORM
primary-key lookup); `category`/`note` are only ever assigned to ORM
attributes, then persisted via `session.commit()` — never raw/
interpolated SQL.
"""

from __future__ import annotations

from typing import Any

MEMORY_CURATE_WRITE_TOOL: dict[str, Any] = {
    "name": "memory_curate_write",
    "description": "Update a memory entry during curation (recategorize, or mark as a superseded duplicate by rewriting its summary to note the supersession). Precursor to the full versioned-lesson lifecycle — light-touch, not a rewrite of history.",
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "MemoryEmbedding row id."},
            "category": {
                "type": "string",
                "description": "New category, if recategorizing.",
            },
            "note": {
                "type": "string",
                "description": "Note to append to the summary, e.g. superseded-by info.",
            },
        },
        "required": ["id"],
    },
}


def memory_curate_write_handler(inp: dict[str, Any]) -> str:
    """Core memory_curate_write logic — real DB write via the canonical
    isolated-engine helper (fixes this tool's own duplicate-helper
    finding), with the `id` coercion now using `.get()` inside its own
    try/except (fixes this tool's own two uncaught-crash findings: a
    missing key AND a malformed value)."""
    import asyncio

    if "id" not in inp:
        return "[ERROR] id is required"
    try:
        row_id = int(inp["id"])
    except (TypeError, ValueError) as exc:
        return f"[ERROR] memory_curate_write: invalid numeric argument for id: {exc}"

    new_category = inp.get("category")
    note = inp.get("note")
    if not new_category and not note:
        return "[ERROR] provide category and/or note — nothing to update"

    async def _update() -> bool:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import MemoryEmbedding
        from app.db.session import new_isolated_async_engine

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await session.get(MemoryEmbedding, row_id)
                if row is None:
                    return False
                if new_category:
                    row.category = str(new_category)
                if note:
                    row.summary = f"{row.summary}\n[curated] {note}"
                await session.commit()
                return True
        finally:
            await engine.dispose()

    try:
        found = asyncio.run(_update())
    except Exception as exc:
        return f"[ERROR] memory_curate_write failed: {exc}"
    if not found:
        return f"[ERROR] No memory entry with id={row_id}"
    return f"Memory entry #{row_id} updated."
