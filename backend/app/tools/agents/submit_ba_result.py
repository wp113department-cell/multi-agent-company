"""submit_ba_result tool — tool_enhance.md productionization pass,
tool #182 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_ba_result
Old path: app/agents/tools.py (`_SUBMIT_BA_RESULT_TOOL` schema dict,
    `ba_submit` inside `make_business_analyst_handlers()` — the one
    real implementation).
New path: app/tools/agents/submit_ba_result.py (this file) —
    `SUBMIT_BA_RESULT_TOOL`, `submit_ba_result_handler`.
Affected agents: exactly 1 per tool_inventory.json —
    `business_analyst` (`app/agents/business_analyst.py`).
    Deliberately NOT in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS`
    membership check — same correct-and-intentional absence already
    established for sibling tools #66/#180/#181.
Affected modules: app/agents/tools.py (`ba_submit` delegates to the
    shared handler; the local `ba_result` dict accumulator and
    `handlers["_ba_result"]` export are removed — see finding).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_ba_result" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — the two existing real tests
    only check tool/handler registration by name, neither reads
    `_ba_result`. New tests added: see
    tests/test_submit_ba_result_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_ba_result.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`user_stories`,
`acceptance_criteria`, `edge_cases`, `summary` are all free-form
structured data) — no injection surface.

One real finding, same class and shape as sibling tools #180/#181:
**dead-code accumulator, never actually read.** `ba_submit`'s
original body did `ba_result.update(inp)`, and the factory separately
exported `handlers["_ba_result"] = ba_result` — but grepping the
entire production codebase found zero real readers. The tool's real,
functioning result-capture mechanism lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`business_analyst.py`'s own `raw = final_state["result"]` line, which
is what real production code actually consumes.

Fixed by removing the dead `ba_result` dict and `_ba_result` export
entirely — `submit_ba_result_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before, with zero behavior change to the
tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_BA_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_ba_result",
    "description": "Submit business analysis: user stories, acceptance criteria, edge cases.",
    "input_schema": {
        "type": "object",
        "properties": {
            "user_stories": {"type": "array", "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "edge_cases": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["user_stories", "summary"],
    },
}


def submit_ba_result_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Business analysis submitted"
