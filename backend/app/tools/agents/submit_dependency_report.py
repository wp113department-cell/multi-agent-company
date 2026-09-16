"""submit_dependency_report tool — tool_enhance.md productionization
pass, tool #185 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_dependency_report
Old path: app/agents/tools.py (`_SUBMIT_DEPENDENCY_REPORT_TOOL` schema
    dict, `dep_submit` inside `make_dependency_agent_handlers()` — the
    one real implementation).
New path: app/tools/agents/submit_dependency_report.py (this file) —
    `SUBMIT_DEPENDENCY_REPORT_TOOL`, `submit_dependency_report_handler`.
Affected agents: exactly 1 per tool_inventory.json —
    `dependency_agent` (`app/agents/dependency_agent.py`). Deliberately
    NOT in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check
    — same correct-and-intentional absence already established for
    sibling tools #66/#180/#181/#182/#183/#184.
Affected modules: app/agents/tools.py (`dep_submit` delegates to the
    shared handler; the local `dep_result` dict accumulator and
    `handlers["_dependency_result"]` export are removed — see finding).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_dependency_report" ToolManifestEntry is pure metadata,
    keyed by tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestDependencyHandlers::
    test_submit_stores_result` asserted directly on the now-removed
    `h["_dependency_result"]` dict (an internal implementation detail,
    not real production behavior — see finding). Updated to assert on
    the handler's real return value instead, preserving the test's
    actual intent (verify a real submission succeeds) without relying
    on dead internal state. `tests/test_gap49_dependency_scan.py`
    imports `_SUBMIT_DEPENDENCY_REPORT_TOOL` directly from
    `app.agents.tools` — unaffected, since that name is kept as a
    verbatim re-export of `SUBMIT_DEPENDENCY_REPORT_TOOL`. New tests
    added: see tests/test_submit_dependency_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_dependency_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`dependencies`,
`summary`, `files_changed` are all free-form structured data — the
agent's real file edits already happened via its own separately
gated `edit_file` handler before this tool is ever called) — no
injection surface. The schema's `manifest_read` field is explicitly
documented (in the schema itself) as "Overridden by the real
VerificationConfig graph-execution state, never trusted from the
model's own claim" — confirmed live: `run_dependency_agent()` reads
`final_state["verification"].get("manifest_read", False)`, NOT
`raw.get("manifest_read")`, so an LLM claiming `manifest_read: true`
without actually having read the manifest cannot forge verification
— already correct, no fix needed there.

Pre-existing history (Gap-closure Day 49, kept for context, not
re-litigated here): the schema previously used a completely different
shape (`{outdated, upgraded, issues, files_changed}`) that matched
neither the role prompt's documented contract nor
`run_dependency_agent()`'s own consuming code, silently discarding
every real finding. That was already fixed before this productionization
pass — re-verified live this turn (a real `dependencies` entry survives
end-to-end through `run_dependency_agent()`'s `raw.get("dependencies",
[])` read), no regression found.

One real finding, same class and shape as sibling tools
#180/#181/#182/#183/#184: **dead-code accumulator, never actually
read.** `dep_submit`'s original body did `dep_result.update(inp)`,
and the factory separately exported `handlers["_dependency_result"] =
dep_result` — but grepping the entire production codebase found zero
real readers (the one match outside this handler was a test asserting
directly on the dead key — see Tests). The tool's real, functioning
result-capture mechanism lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`run_dependency_agent()`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `dep_result` dict and
`_dependency_result` export entirely — `submit_dependency_report_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Dependency report
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_DEPENDENCY_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_dependency_report",
    "description": "Submit dependency upgrade analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "current_version": {"type": "string"},
                        "latest_version": {"type": "string"},
                        "vulnerability_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "upgrade_recommended": {"type": "boolean"},
                        "breaking_changes": {"type": "string"},
                        "abandoned": {
                            "type": "boolean",
                            "description": "True if check_last_release showed no release in a long time (not merely 'not the newest version') — only set when check_last_release was actually called for this package this run.",
                        },
                        "last_release_days_ago": {
                            "type": "integer",
                            "description": "Days since the latest published release, from this run's real check_last_release output.",
                        },
                    },
                    "required": [
                        "name",
                        "current_version",
                        "latest_version",
                        "upgrade_recommended",
                    ],
                },
            },
            "summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "manifest_read": {
                "type": "boolean",
                "description": "Overridden by the real VerificationConfig graph-execution state, never trusted from the model's own claim.",
            },
        },
        "required": ["dependencies", "summary", "manifest_read"],
    },
}


def submit_dependency_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Dependency report submitted"
