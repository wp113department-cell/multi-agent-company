"""submit_migration tool — tool_enhance.md productionization pass,
tool #188 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_migration
Old path: app/agents/tools.py (`_SUBMIT_MIGRATION_TOOL` schema dict,
    `mg_submit` inside `make_migration_agent_handlers()` — the one
    real implementation).
New path: app/tools/agents/submit_migration.py (this file) —
    `SUBMIT_MIGRATION_TOOL`, `submit_migration_handler`.
Affected agents: exactly 1 per tool_inventory.json — `migration_agent`
    (`app/agents/migration_agent.py`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — same
    correct-and-intentional absence already established for sibling
    tools #66/#180-#186.
Affected modules: app/agents/tools.py (`mg_submit` delegates to the
    shared handler; the local `migration_result` dict accumulator and
    `handlers["_migration_result"]` export are removed — see finding).
    `make_migration_agent_handlers()`'s other handlers (`run_sql`,
    `inspect_schema`, `write_file`, `bash`) are each their own
    separately-productionized concern — deliberately untouched here,
    out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_migration" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day3_agents.py::TestMigrationAgentTools`
    and `::TestMigrationAgentHandlers` assert only tool-list membership
    and handler-key presence — neither references the internal
    `_migration_result` dict, so no fix was required there (same as
    tool #184). New tests added: see
    tests/test_submit_migration_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_migration.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`migration_file` is a
free-form string describing a path already written via the agent's
own separately gated `write_file` handler before this tool is ever
called; `is_reversible`/`summary`/`warnings` are plain
booleans/strings) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186: **dead-code accumulator, never actually read.**
`mg_submit`'s original body did `migration_result.update(inp)`, and
the factory separately exported `handlers["_migration_result"] =
migration_result` — but grepping the entire production codebase found
zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `migration_agent.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `migration_result` dict and
`_migration_result` export entirely — `submit_migration_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Migration
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_MIGRATION_TOOL: dict[str, Any] = {
    "name": "submit_migration",
    "description": "Submit the generated migration file path and validation results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "migration_file": {"type": "string"},
            "is_reversible": {"type": "boolean"},
            "summary": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}


def submit_migration_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Migration submitted"
