"""submit_sprint_plan tool — tool_enhance.md productionization pass,
tool #198 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_sprint_plan
Old path: app/agents/tools.py (`_SUBMIT_SPRINT_PLAN_TOOL` schema dict,
    `sp_submit` inside `make_sprint_planner_handlers()` — the one real
    implementation).
New path: app/tools/agents/submit_sprint_plan.py (this file) —
    `SUBMIT_SPRINT_PLAN_TOOL`, `submit_sprint_plan_handler`.
Affected agents: exactly 1 per tool_inventory.json — `sprint_planner`
    (`app/agents/sprint_planner.py`). Deliberately NOT in `CHAT_TOOLS`
    — confirmed via `CHAT_TOOLS` membership check — same correct-and-
    intentional absence already established for sibling tools
    #66/#180-#186/#188-#192/#194/#196/#197.
Affected modules: app/agents/tools.py (`sp_submit` delegates to the
    shared handler; the local `sprint_result` dict accumulator and
    `handlers["_sprint_result"]` export are removed — see finding).
    `make_sprint_planner_handlers()`'s other handler
    (`estimate_complexity`) is its own separately-productionized tool
    (already GREEN_FLAGGED as tool #110) — deliberately untouched
    here, out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_sprint_plan" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day3_agents.py::TestSprintPlannerTools`
    and `::TestSprintPlannerHandlers` assert only tool-list membership
    and handler-key presence — neither references the internal
    `_sprint_result` dict, so no fix was required there (same shape as
    tool #184). New tests added: see
    tests/test_submit_sprint_plan_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_sprint_plan.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`goal`, `stories`,
`total_points`, `risks` are all free-form structured data — the agent
is read-only plus `estimate_complexity`, no write/bash/SQL capability
anywhere for this input to reach) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196/#197: **dead-code accumulator, never actually
read.** `sp_submit`'s original body did `sprint_result.update(inp)`,
and the factory separately exported `handlers["_sprint_result"] =
sprint_result` — but grepping the entire production codebase found
zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `sprint_planner.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `sprint_result` dict and `_sprint_result`
export entirely — `submit_sprint_plan_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before (`"Sprint plan submitted"`), with zero
behavior change to the tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_SPRINT_PLAN_TOOL: dict[str, Any] = {
    "name": "submit_sprint_plan",
    "description": "Submit a sprint plan with stories and estimates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "stories": {"type": "array", "items": {"type": "object"}},
            "total_points": {"type": "integer"},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goal", "stories"],
    },
}


def submit_sprint_plan_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Sprint plan submitted"
