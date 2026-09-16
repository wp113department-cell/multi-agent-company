"""submit_research tool — tool_enhance.md productionization pass,
tool #193 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_research
Old path: app/agents/tools.py (`_SUBMIT_RESEARCH_TOOL` schema dict,
    `submit_research` closure inside `make_research_handlers()` — the
    one real implementation).
New path: app/tools/agents/submit_research.py (this file) —
    `SUBMIT_RESEARCH_TOOL`, `make_submit_research_handler`.
Affected agents: exactly 1 per tool_inventory.json — `research`
    (`app/agents/research.py`, via `run_research()`). Deliberately NOT
    in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check —
    same correct-and-intentional absence already established for
    sibling tools #66/#180-#186/#188-#192.
Affected modules: app/agents/tools.py (`make_research_handlers()`'s
    inline `submit_research` closure now delegates to
    `make_submit_research_handler(research_result)`, mirroring the
    already-established `make_submit_docs_handler(docs_result)` /
    `make_submit_health_report_handler(health_result)` /
    `make_submit_qa_result_handler(qa_result)` pattern from tools
    #85/#187/#191 — the shared `web_search` entry in the same factory
    function is untouched, out of scope for this tool's turn, already
    productionized separately as tool #88).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_research" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — `tests/test_session4_migration.py`
    patches `make_research_handlers` to return `{"_research_result": ...}`
    and verifies `run_research()`'s consumption of it (on both a
    populated and an empty dict) — already correct. New tests added:
    see tests/test_submit_research_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_research.md.
---------------------------------------------------------------------------

IMPORTANT DIFFERENCE FROM SIBLING TOOLS #180-#186/#188-#190/#192 (same
class as tools #187/#191): this is NOT a dead accumulator. `run_research()`
reads `handlers.get("_research_result", {})` directly — confirmed by
reading the full function body, including its explicit
"Research agent did not call submit_research" fallback error when the
dict is empty. `run_research()` does NOT use `run_agent_graph`'s
generic `final_state["result"]` submit_* capture at all for this
agent — it also separately tracks `research_submitted` via
`VerificationConfig.set_by`, an independent verification signal from
the result-content dict itself. No dead-code finding here — the
opposite of tools #180-#186/#188-#190/#192's finding class.

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`findings`,
`relevantLibraries`, `recommendedApproach`, `risks` are all free-form
structured/string data — the agent's real research already happened
via its own separately gated `read_file`/`search_code`/`web_search`
handlers before this tool is ever called) — no injection surface.

No functional bug found. Modularized purely for consistency with the
already-established `make_submit_docs_handler`/
`make_submit_health_report_handler`/`make_submit_qa_result_handler`
pattern (tools #85/#187/#191) — the factory takes the
externally-owned `research_result` dict (created and exported by
`make_research_handlers()`) rather than owning it itself, preserving
the exact existing contract `run_research()` relies on.
"""

from __future__ import annotations

from typing import Any, Callable

SUBMIT_RESEARCH_TOOL: dict[str, Any] = {
    "name": "submit_research",
    "description": "Submit the final research report with findings, library recommendations, approach, and risks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key findings from the research",
            },
            "relevantLibraries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "rationale"],
                },
            },
            "recommendedApproach": {"type": "string"},
            "risks": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["findings", "relevantLibraries", "recommendedApproach", "risks"],
    },
}


def make_submit_research_handler(
    research_result: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    """Core submit_research logic for the one real call site.

    `research_result` is the per-agent-instance dict
    `make_research_handlers()` already creates and exposes as
    `handlers["_research_result"]` — this function does not own or
    create that dict, matching the existing contract
    `app/agents/research.py::run_research` relies on to build its real
    `ResearchReport` return value.
    """

    def submit_research_handler(inp: dict[str, Any]) -> str:
        research_result.update(inp)
        return "Research report submitted"

    return submit_research_handler
