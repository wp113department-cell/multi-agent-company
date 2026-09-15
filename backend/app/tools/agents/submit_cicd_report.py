"""submit_cicd_report tool — tool_enhance.md productionization pass,
tool #183 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_cicd_report
Old path: app/agents/tools.py (`_SUBMIT_CICD_REPORT_TOOL` schema
    dict, `ci_submit` inside `make_cicd_agent_handlers()` — the one
    real implementation).
New path: app/tools/agents/submit_cicd_report.py (this file) —
    `SUBMIT_CICD_REPORT_TOOL`, `submit_cicd_report_handler`.
Affected agents: exactly 1 per tool_inventory.json — `cicd_agent`
    (`app/agents/cicd_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
    confirmed via `CHAT_TOOLS` membership check — same correct-and-
    intentional absence already established for sibling tools
    #66/#180/#181/#182.
Affected modules: app/agents/tools.py (`ci_submit` delegates to the
    shared handler; the local `cicd_result` dict accumulator and
    `handlers["_cicd_result"]` export are removed — see finding).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_cicd_report" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestCicdHandlers::
    test_submit_stores_result` asserted directly on the now-removed
    `h["_cicd_result"]` dict (an internal implementation detail, not
    real production behavior — see finding). Updated to assert on
    the handler's real return value instead, preserving the test's
    actual intent (verify a real submission succeeds) without
    relying on dead internal state. New tests added: see
    tests/test_submit_cicd_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_cicd_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`analysis`,
`files_written`, `recommendations` are all free-form structured
data) — no injection surface.

One real finding, same class and shape as sibling tools
#180/#181/#182: **dead-code accumulator, never actually read.**
`ci_submit`'s original body did `cicd_result.update(inp)`, and the
factory separately exported `handlers["_cicd_result"] = cicd_result`
— but grepping the entire production codebase found zero real
readers. The tool's real, functioning result-capture mechanism lives
entirely in `app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`cicd_agent.py`'s own `raw = final_state["result"]` line, which is
what real production code actually consumes.

A sibling handler in the same factory function's neighborhood
(`submit_refactor_report`'s `_refactor_result`, a DIFFERENT tool not
yet reached in this initiative) follows the identical historical
pattern — deliberately NOT touched here, to be independently audited
and fixed on its own turn.

Fixed by removing the dead `cicd_result` dict and `_cicd_result`
export entirely — `submit_cicd_report_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before, with zero behavior change to the
tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_CICD_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_cicd_report",
    "description": "Submit CI/CD agent analysis or workflow changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["analysis"],
    },
}


def submit_cicd_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "CI/CD report submitted"
