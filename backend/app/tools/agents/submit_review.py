"""submit_review tool — tool_enhance.md productionization pass, tool
#195 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_review
Old path: app/agents/tools.py (`_SUBMIT_REVIEW_TOOL` schema dict,
    `submit_review` closure inside `make_reviewer_handlers()` — the
    one real implementation).
New path: app/tools/agents/submit_review.py (this file) —
    `SUBMIT_REVIEW_TOOL`, `make_submit_review_handler`.
Affected agents: exactly 1 per tool_inventory.json — `reviewer`
    (`app/agents/reviewer.py`, via `run_reviewer()`). Deliberately NOT
    in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check —
    same correct-and-intentional absence already established for
    sibling tools #66/#180-#186/#188-#192/#194.
Affected modules: app/agents/tools.py (`make_reviewer_handlers()`'s
    inline `submit_review` closure now delegates to
    `make_submit_review_handler(review_result)`, mirroring the
    already-established `make_submit_docs_handler(docs_result)` /
    `make_submit_health_report_handler(health_result)` /
    `make_submit_qa_result_handler(qa_result)` /
    `make_submit_research_handler(research_result)` pattern from tools
    #85/#187/#191/#193 — `make_reviewer_handlers()` has no other real
    entries besides the inherited read-only handlers, so nothing else
    in that factory needed touching).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_review" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — `tests/test_session3_migration.py`
    (patches `_review_result` directly and verifies `run_reviewer()`'s
    consumption of it, on both a populated and an empty dict — already
    correct; also explicitly tracks `submit_review` in its own
    `_SUBMIT_PRIVATE` set alongside `submit_qa_result`/
    `submit_health_report`, the same real-accumulator class),
    `tests/test_tool_scoping.py` (tool-name membership in
    `REVIEWER_TOOLS`, unaffected), and `tests/test_fleet_tool_manifest.py`
    (manifest entry name, unaffected). New tests added: see
    tests/test_submit_review_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_review.md.
---------------------------------------------------------------------------

IMPORTANT DIFFERENCE FROM SIBLING TOOLS #180-#186/#188-#190/#192 (same
class as tools #187/#191/#193): this is NOT a dead accumulator.
`run_reviewer()` reads `handlers.get("_review_result", {})` directly
— confirmed by reading the full function body, including the
exception-path fallback (a real agent-run failure produces a synthetic
"blocking" finding instead of ever touching `_review_result`) and the
normal-completion path immediately after. `run_reviewer()` does NOT
use `run_agent_graph`'s generic `final_state["result"]` submit_*
capture at all for this agent. No dead-code finding here — the
opposite of tools #180-#186/#188-#190/#192's finding class.

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`findings` is free-form
structured data, `verdict`/`summary` are strings — the agent is
read-only, no filesystem/network/SQL capability exists anywhere in
`make_reviewer_handlers()` for this tool's own input to reach) — no
injection surface.

No functional bug found. Modularized purely for consistency with the
already-established `make_submit_docs_handler`/
`make_submit_health_report_handler`/`make_submit_qa_result_handler`/
`make_submit_research_handler` pattern (tools #85/#187/#191/#193) —
the factory takes the externally-owned `review_result` dict (created
and exported by `make_reviewer_handlers()`) rather than owning it
itself, preserving the exact existing contract `run_reviewer()`
relies on.
"""

from __future__ import annotations

from typing import Any, Callable

SUBMIT_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_review",
    "description": "Submit the structured code review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["blocking", "non-blocking", "suggestion"],
                        },
                        "file": {"type": "string"},
                        "line": {"type": ["integer", "null"]},
                        "finding": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["severity", "file", "finding", "recommendation"],
                },
            },
            "verdict": {"type": "string", "enum": ["approved", "changes_required"]},
            "summary": {"type": "string"},
        },
        "required": ["findings", "verdict", "summary"],
    },
}


def make_submit_review_handler(
    review_result: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    """Core submit_review logic for the one real call site.

    `review_result` is the per-agent-instance dict
    `make_reviewer_handlers()` already creates and exposes as
    `handlers["_review_result"]` — this function does not own or
    create that dict, matching the existing contract
    `app/agents/reviewer.py::run_reviewer` relies on to build its real
    `ReviewResult` return value.
    """

    def submit_review_handler(inp: dict[str, Any]) -> str:
        review_result.update(inp)
        return "Review submitted"

    return submit_review_handler
