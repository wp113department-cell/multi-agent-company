"""memory_search tool — tool_enhance.md productionization pass,
tool #227 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_search
Old path: app/agents/tools.py (`_MEMORY_SEARCH_TOOL` schema dict,
    module-level `memory_search()` function).
New path: app/tools/agents/memory_search.py (this file) —
    `MEMORY_SEARCH_TOOL`, `memory_search_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `knowledge_curator` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import memory_search` unchanged.
Affected tests: `tests/test_cluster_o_phase1d_memory_search_tool.py`
    (4 tests, all real-DB — schema, cross-repo leak-proofing,
    fleet-wide default, required-query regression) already exercises
    this tool thoroughly — re-run and confirmed passing unchanged. New
    tests added: see tests/test_memory_search_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_search.md.
---------------------------------------------------------------------------

Two real findings, the same class already found and fixed on the rest
of this memory-tool family (`memory_curate_read` #223,
`memory_curate_write` #224, `memory_list_draft_lessons` #225):

1. TWO separate uncaught-crash paths, both happening BEFORE the
   function's own `try: results = asyncio.run(_search()) except
   Exception: return "[ERROR] ..."` block:
   `top_k = int(inp.get("top_k", 5))` and
   `repo_id = int(repo_id_raw) if repo_id_raw is not None else None`.
   Proved live, before any fix:
   `memory_search({"query": "x", "top_k": "not-a-number"})` and
   `memory_search({"query": "x", "repo_id": "not-a-number"})` both
   raised an uncaught `ValueError`. Fixed by moving both coercions
   inside the guard.

2. Used the local, less-completely-configured
   `_new_isolated_db_engine()` instead of the canonical
   `app.db.session.new_isolated_async_engine()`. Fixed for this tool
   specifically — this is the last of the 4 memory tools this
   initiative flagged as using the local duplicate
   (`memory_curate_read`, `memory_curate_write`,
   `memory_list_draft_lessons`, and this one), closing out the family.

No SQL injection surface: `query`/`top_k`/`repo_id` only ever reach
`app.memory.store.query_similar_tasks()`'s own parametrized pgvector
similarity search — never raw/interpolated SQL.
"""

from __future__ import annotations

from typing import Any

MEMORY_SEARCH_TOOL: dict[str, Any] = {
    "name": "memory_search",
    "description": "Semantic search over the fleet's persistent engineering memory (past task outcomes, architecture decisions, failures, lessons) — NOT the same as memory_read/memory_write (those are a different, per-repo scratch store). Searches fleet-wide (across every repo) by default — pass repo_id only to narrow to one specific repo's own memories plus fleet-wide/legacy ones.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "top_k": {"type": "integer", "description": "Max results (default 5)."},
            "repo_id": {
                "type": "integer",
                "description": "Stage 4 Cluster O Phase 1d (2026-08-05): optional — restrict "
                "results to this repo's own memories plus fleet-wide/legacy ones. Omit to "
                "search fleet-wide (the default, and the right choice for this tool's real "
                "caller, knowledge_curator, whose job is curating memory across the whole "
                "fleet, not one repo).",
            },
        },
        "required": ["query"],
    },
}


def memory_search_handler(inp: dict[str, Any]) -> str:
    """Core memory_search logic — real pgvector similarity search via
    the canonical isolated-engine helper (fixes this tool's own
    duplicate-helper finding), with the numeric `top_k`/`repo_id`
    coercions now inside their own try/except (fixes this tool's own
    two uncaught-crash findings)."""
    import asyncio

    query = str(inp.get("query", "")).strip()
    if not query:
        return "[ERROR] query is required"

    async def _search() -> list[dict[str, Any]]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.session import new_isolated_async_engine
        from app.memory.store import query_similar_tasks

        top_k = int(inp.get("top_k", 5))
        repo_id_raw = inp.get("repo_id")
        repo_id: int | None = int(repo_id_raw) if repo_id_raw is not None else None

        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await query_similar_tasks(
                    description=query, db=session, top_k=top_k, repo_id=repo_id
                )
        finally:
            await engine.dispose()

    try:
        results = asyncio.run(_search())
    except (TypeError, ValueError) as exc:
        return f"[ERROR] memory_search: invalid numeric argument for top_k/repo_id: {exc}"
    except Exception as exc:
        return f"[ERROR] memory_search failed: {exc}"
    if not results:
        return "(no similar memories found)"
    lines = [
        f"[{r.get('similarity', 0):.2f}] task={r.get('task_id')} outcome={r.get('outcome')} — {str(r.get('summary', ''))[:200]}"
        for r in results
    ]
    return "\n".join(lines)
