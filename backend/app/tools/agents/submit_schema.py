"""submit_schema tool — tool_enhance.md productionization pass, tool
#196 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_schema
Old path: app/agents/tools.py (`_SUBMIT_SCHEMA_TOOL` schema dict,
    `sa_submit` inside `make_schema_agent_handlers()` — the one real
    implementation).
New path: app/tools/agents/submit_schema.py (this file) —
    `SUBMIT_SCHEMA_TOOL`, `submit_schema_handler`.
Affected agents: exactly 1 per tool_inventory.json — `schema_agent`
    (`app/agents/schema_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
    confirmed via `CHAT_TOOLS` membership check — same correct-and-
    intentional absence already established for sibling tools
    #66/#180-#186/#188-#192/#194.
Affected modules: app/agents/tools.py (`sa_submit` delegates to the
    shared handler; the local `schema_result` dict accumulator and
    `handlers["_schema_result"]` export are removed — see finding).
    `make_schema_agent_handlers()`'s other handlers (`run_sql`,
    `inspect_schema`, `write_file`) are each their own separately-
    productionized concern (`inspect_schema` already GREEN_FLAGGED as
    tool #96) — deliberately untouched here, out of scope for this
    tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_schema" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: `tests/test_day3_agents.py::TestSchemaAgentTools` and
    `::TestSchemaAgentHandlers` assert only tool-list membership and
    handler-key presence — neither references the internal
    `_schema_result` dict, so no fix was required there (same shape as
    tool #184). A same-named-substring match in
    `tests/test_stage4_cluster_q_test_coverage_pct.py::
    test_submit_schema_declares_optional_nullable_coverage_pct` is a
    false positive from grep's exact-string matching — that test
    covers `test_coverage_agent`'s own unrelated `_SUBMIT` schema, not
    this tool at all (verified by reading it). New tests added: see
    tests/test_submit_schema_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_schema.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`summary`, `tables`,
`normalization_issues`, `files_written` are all free-form structured
data — any real schema file write already happened via the agent's
own separately gated `write_file` handler before this tool is ever
called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188-#192: **dead-code accumulator, never actually read.**
`sa_submit`'s original body did `schema_result.update(inp)`, and the
factory separately exported `handlers["_schema_result"] =
schema_result` — but grepping the entire production codebase found
zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `schema_agent.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `schema_result` dict and `_schema_result`
export entirely — `submit_schema_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"Schema design submitted"`), with
zero behavior change to the tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_SCHEMA_TOOL: dict[str, Any] = {
    "name": "submit_schema",
    "description": "Submit a schema design or review result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tables": {"type": "array", "items": {"type": "object"}},
            "normalization_issues": {"type": "array", "items": {"type": "string"}},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}


def submit_schema_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Schema design submitted"
