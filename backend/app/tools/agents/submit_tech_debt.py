"""submit_tech_debt tool — tool_enhance.md productionization pass,
tool #201 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_tech_debt
Old path: app/agents/tools.py (`_SUBMIT_TECH_DEBT_TOOL` schema dict,
    `td_submit` inside `make_tech_debt_agent_handlers()` — the one
    real implementation).
New path: app/tools/agents/submit_tech_debt.py (this file) —
    `SUBMIT_TECH_DEBT_TOOL`, `submit_tech_debt_handler`.
Affected agents: exactly 1 per tool_inventory.json — `tech_debt_agent`
    (`app/agents/tech_debt_agent.py`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — same
    correct-and-intentional absence already established for sibling
    tools #66/#180-#186/#188-#192/#194/#196-#200.
Affected modules: app/agents/tools.py (`td_submit` delegates to the
    shared handler; the local `tech_debt_result` dict accumulator and
    `handlers["_tech_debt_result"]` export are removed — see finding).
    `make_tech_debt_agent_handlers()`'s other handlers
    (`list_functions`, `list_classes`, `find_todos`, `run_linter`,
    `coverage_report`) are each their own separately-productionized
    concern (`list_functions`/`list_classes`/`run_linter`/
    `coverage_report` already GREEN_FLAGGED as tools #82/#87/#101/#104)
    — deliberately untouched here, out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_tech_debt" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day3_agents.py::TestTechDebtAgentTools`
    and `::TestTechDebtAgentHandlers` assert only tool-list membership
    and handler-key presence — neither references the internal
    `_tech_debt_result` dict, so no fix was required there (same shape
    as tool #184). New tests added: see
    tests/test_submit_tech_debt_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_tech_debt.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`summary`, `debt_items`,
`priority_fixes`, `effort_estimate` are all free-form structured/
string data — any real analysis already happened via the agent's own
separately gated `list_functions`/`list_classes`/`find_todos`/
`run_linter`/`coverage_report` handlers before this tool is ever
called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196-#200: **dead-code accumulator, never actually
read.** `td_submit`'s original body did `tech_debt_result.update(inp)`,
and the factory separately exported `handlers["_tech_debt_result"] =
tech_debt_result` — but grepping the entire production codebase found
zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `tech_debt_agent.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `tech_debt_result` dict and
`_tech_debt_result` export entirely — `submit_tech_debt_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Tech debt analysis
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_TECH_DEBT_TOOL: dict[str, Any] = {
    "name": "submit_tech_debt",
    "description": "Submit technical debt analysis findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "debt_items": {"type": "array", "items": {"type": "object"}},
            "priority_fixes": {"type": "array", "items": {"type": "string"}},
            "effort_estimate": {"type": "string"},
        },
        "required": ["summary"],
    },
}


def submit_tech_debt_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Tech debt analysis submitted"
