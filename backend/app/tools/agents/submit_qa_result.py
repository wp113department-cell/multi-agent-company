"""submit_qa_result tool — tool_enhance.md productionization pass,
tool #191 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_qa_result
Old path: app/agents/tools.py (`_SUBMIT_QA_TOOL` schema dict,
    `submit_qa_result` closure inside `make_qa_handlers()` — the one
    real implementation).
New path: app/tools/agents/submit_qa_result.py (this file) —
    `SUBMIT_QA_RESULT_TOOL`, `make_submit_qa_result_handler`.
Affected agents: exactly 1 per tool_inventory.json — `qa`
    (`app/agents/qa.py`, via `run_qa()`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — same
    correct-and-intentional absence already established for sibling
    tools #66/#180-#186/#188-#190.
Affected modules: app/agents/tools.py (`make_qa_handlers()`'s inline
    `submit_qa_result` closure now delegates to
    `make_submit_qa_result_handler(qa_result)`, mirroring the
    already-established `make_submit_docs_handler(docs_result)` /
    `make_submit_health_report_handler(health_result)` pattern from
    tools #85/#187 — the shared `bash` closure in the same factory
    function is untouched, out of scope for this tool's turn).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_qa_result" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — `tests/test_session3_migration.py`
    (patches `make_qa_handlers` to return `{"_qa_result": ...}` and
    verifies `run_qa()`'s consumption of it), `tests/test_tool_scoping.py`,
    and `tests/test_fleet_tool_manifest.py` all access this tool via
    the real, preserved `handlers["_qa_result"]` export or tool-name
    membership — none needed a change. New tests added: see
    tests/test_submit_qa_result_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_qa_result.md.
---------------------------------------------------------------------------

IMPORTANT DIFFERENCE FROM SIBLING TOOLS #180-#186/#188-#190 (same
class as tool #187's submit_health_report): this is NOT a dead
accumulator. `run_qa()` reads `handlers.get("_qa_result", {})`
directly — confirmed by reading the full function body, including
BOTH the success path (`raw = handlers.get("_qa_result", {})` after a
normal submit) AND the turn-limit-exhausted retry-giveup path (same
read, used to salvage a partial result even when the agent never
finished). `run_qa()` does NOT use `run_agent_graph`'s generic
`final_state["result"]` submit_* capture at all for this agent. No
dead-code finding here — the opposite of tools #180-#186/#188-#190's
finding class.

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`status` is an enum,
`tests_run`/`tests_passed`/`tests_failed` are integers,
`typecheck_clean`/`lint_clean` are booleans, `errors` is a string
array, `summary` is a string — all self-reported structured data from
checks the agent already ran via its own separately gated `bash`
handler) — no injection surface.

No functional bug found. Modularized purely for consistency with the
already-established `make_submit_docs_handler`/`make_submit_health_report_handler`
pattern (tools #85/#187) — the factory takes the externally-owned
`qa_result` dict (created and exported by `make_qa_handlers()`) rather
than owning it itself, preserving the exact existing contract every
real downstream consumer (`app/agents/qa.py::run_qa`, on both its
success and retry-giveup paths) relies on.
"""

from __future__ import annotations

from typing import Any, Callable

SUBMIT_QA_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_qa_result",
    "description": "Submit the final QA result after all checks are complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["passed", "failed"]},
            "tests_run": {"type": "integer"},
            "tests_passed": {"type": "integer"},
            "tests_failed": {"type": "integer"},
            "typecheck_clean": {"type": "boolean"},
            "lint_clean": {"type": "boolean"},
            "errors": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": [
            "status",
            "tests_run",
            "tests_passed",
            "tests_failed",
            "typecheck_clean",
            "lint_clean",
            "errors",
            "summary",
        ],
    },
}


def make_submit_qa_result_handler(
    qa_result: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    """Core submit_qa_result logic for the one real call site.

    `qa_result` is the per-agent-instance dict `make_qa_handlers()`
    already creates and exposes as `handlers["_qa_result"]` — this
    function does not own or create that dict, matching the existing
    contract `app/agents/qa.py::run_qa` relies on (on both its normal
    success path and its turn-limit-exhausted retry-giveup path) to
    build its real `QAResult` return value.
    """

    def submit_qa_result_handler(inp: dict[str, Any]) -> str:
        qa_result.update(inp)
        return "QA result submitted"

    return submit_qa_result_handler
