"""submit_refactor_report tool — tool_enhance.md productionization
pass, tool #192 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_refactor_report
Old path: app/agents/tools.py (`_SUBMIT_REFACTOR_REPORT_TOOL` schema
    dict, `rf_submit` inside `make_refactor_agent_handlers()` — the
    one real implementation).
New path: app/tools/agents/submit_refactor_report.py (this file) —
    `SUBMIT_REFACTOR_REPORT_TOOL`, `submit_refactor_report_handler`.
Affected agents: exactly 1 per tool_inventory.json — `refactor_agent`
    (`app/agents/refactor_agent.py`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — same
    correct-and-intentional absence already established for sibling
    tools #66/#180-#186/#188-#191.
Affected modules: app/agents/tools.py (`rf_submit` delegates to the
    shared handler; the local `refactor_result` dict accumulator and
    `handlers["_refactor_result"]` export are removed — see finding).
    `make_refactor_agent_handlers()`'s other handlers (`list_functions`,
    `list_classes`, `find_function_body`, `parse_ast`, `call_graph`,
    `import_graph`, `rename_symbol`, `replace_function`, `edit_file`,
    `write_file`, `git_diff`, `bash`) are each their own separately-
    productionized tool (most already GREEN_FLAGGED — see the
    tool_enhance.md comments still attached to them in tools.py) —
    deliberately untouched here, out of scope for this tool's turn.
    Note: this is the exact sibling tool `submit_cicd_report`'s own
    docstring (tool #183) explicitly named as sharing its
    dead-accumulator pattern but deliberately not fixed there — this
    turn closes that deferred item.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_refactor_report" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestRefactorHandlers::
    test_submit_stores_result` asserted directly on the now-removed
    `h["_refactor_result"]` dict (an internal implementation detail,
    not real production behavior — see finding). Updated to assert on
    the handler's real return value instead, preserving the test's
    actual intent (verify a real submission succeeds) without relying
    on dead internal state. New tests added: see
    tests/test_submit_refactor_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_refactor_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`summary`,
`files_changed`, `breaking_changes` are all free-form structured data
— any real refactor already happened via the agent's own separately
gated `edit_file`/`write_file`/`rename_symbol`/`replace_function`
handlers before this tool is ever called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188-#191: **dead-code accumulator, never actually read.**
`rf_submit`'s original body did `refactor_result.update(inp)`, and the
factory separately exported `handlers["_refactor_result"] =
refactor_result` — but grepping the entire production codebase found
zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `refactor_agent.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `refactor_result` dict and
`_refactor_result` export entirely — `submit_refactor_report_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Refactor report
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_REFACTOR_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_refactor_report",
    "description": "Submit refactoring agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "breaking_changes": {"type": "boolean"},
        },
        "required": ["summary", "files_changed"],
    },
}


def submit_refactor_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Refactor report submitted"
