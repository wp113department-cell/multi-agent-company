"""record_learning tool — tool_enhance.md productionization pass, tool
#66 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: record_learning
Old path: app/agents/tools.py (`RECORD_LEARNING_TOOL` schema dict and
    `make_record_learning_handler()` factory).
New path: app/tools/agents/record_learning.py (this file) — same names,
    moved verbatim.
Affected agents: per tool_inventory.json, 81 agents declare
    `record_learning` in `allowed_tools` — genuinely ONE real
    implementation (a single factory function, parametrized per calling
    agent's own name), not 81 separate ones; confirmed by grepping every
    `make_record_learning_handler(...)` call site (~80+, all in
    `run_agent_graph`-based one-shot agent modules). This tool is
    deliberately NOT in `CHAT_TOOLS` — verified `chat_agent.py` has zero
    reference to it at all — it is a fleet-governance memory-write tool
    scoped to specific one-shot agent identities, with no interactive-
    session use case; this is a correct, intentional absence, not a
    missed dispatch (the "advertised but never dispatched" bug class
    found repeatedly this initiative does not apply here since it was
    never advertised to chat in the first place).
Affected modules: app/agents/tools.py (re-exports both names for the
    ~80 call sites and the several `*_TOOLS` list literals that
    reference `RECORD_LEARNING_TOOL` directly).
Affected registries: none — app/fleet/tool_manifest.py's
    "record_learning" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via `make_record_learning_handler(...)`. New
    tests added: see tests/test_record_learning_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/record_learning.md.
---------------------------------------------------------------------------

Audited for the finding classes this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched) — none apply. `finding`/
`outcome` reach `embed_learning_signal()` as plain string content,
embedded via a vector-embedding call and inserted through the ORM
(`MemoryEmbedding`), never string-interpolated into raw SQL or a shell
command; there is no filesystem path or network destination anywhere in
this tool's input schema, so there is no worktree-escape or SSRF surface
either. `agent_name` (the one value that could theoretically matter for
attribution integrity) is NEVER LLM-controlled — every real call site
passes a static string literal or `AGENT_CONTRACT["name"]` (a fixed
constant from that agent's own contract file), confirmed by reading
every one of the ~80 call sites' actual arguments, not just their
count. The sync/async bridge (`embed_learning_signal_sync` in
`app/memory/store.py`) already uses `new_isolated_async_engine()` +
its own `asyncio.run()`, matching this initiative's own established
"never `asyncio.run()` against the shared `app.db.session` engine from
sync code" rule — already correct, not a violation. No fix required;
this turn is pure modularization plus real verification that the
above holds, not assumed from reading alone.
"""

from __future__ import annotations

from typing import Any, Callable

RECORD_LEARNING_TOOL: dict[str, Any] = {
    "name": "record_learning",
    "description": (
        "Record a non-obvious finding for future agents working on similar tasks. "
        "Use this for something a plain code search would not surface on its own — "
        "a root cause, a workaround, a gotcha — not for routine progress notes. "
        "This writes to shared, durable, cross-agent memory; it does not replace "
        "your normal submit_* result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "finding": {
                "type": "string",
                "description": "The non-obvious insight, in one or two sentences.",
            },
            "outcome": {
                "type": "string",
                "description": "What this finding led to, or why it mattered.",
            },
        },
        "required": ["finding"],
    },
}


def make_record_learning_handler(agent_name: str) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for record_learning, scoped to the calling
    agent's own name so the stored signal is correctly attributed."""

    def _handler(inp: dict[str, Any]) -> str:
        finding = str(inp.get("finding", "")).strip()
        if not finding:
            return "[ERROR] finding is required."
        outcome = (
            str(inp.get("outcome", "")).strip() or "recorded during task execution"
        )

        from app.memory.store import embed_learning_signal_sync

        stored = embed_learning_signal_sync(
            agent_name=agent_name, description=finding, outcome_summary=outcome
        )
        return "Recorded." if stored else "[ERROR] failed to record learning."

    return _handler
