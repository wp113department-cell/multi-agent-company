"""submit_arch_review tool — tool_enhance.md productionization pass,
tool #181 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_arch_review
Old path: app/agents/tools.py (`_SUBMIT_ARCH_REVIEW_TOOL` schema dict,
    `ar_submit` inside `make_arch_reviewer_handlers()` — the one real
    implementation).
New path: app/tools/agents/submit_arch_review.py (this file) —
    `SUBMIT_ARCH_REVIEW_TOOL`, `submit_arch_review_handler`.
Affected agents: exactly 1 per tool_inventory.json —
    `architecture_reviewer` (`app/agents/architecture_reviewer.py`,
    via both `run_arch_review()` and `make_scan_handlers()`).
    Deliberately NOT in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS`
    membership check — same correct-and-intentional absence already
    established for sibling tools #66/#180.
Affected modules: app/agents/tools.py (`ar_submit` delegates to the
    shared handler; the local `arch_result` dict accumulator and
    `handlers["_arch_result"]` export are removed — see finding).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_arch_review" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestArchReviewerHandlers::
    test_submit_stores_result` asserted directly on the now-removed
    `h["_arch_result"]` dict (an internal implementation detail, not
    real production behavior — see finding). Updated to assert on the
    handler's real return value instead, preserving the test's actual
    intent (verify a real submission succeeds) without relying on
    dead internal state. New tests added: see
    tests/test_submit_arch_review_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_arch_review.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`structure_summary`,
`risks`, `recommendations`, `blast_radius`, `import_graph_ran` are
all free-form structured data or a bool) — no injection surface. The
schema's `import_graph_ran` field is explicitly documented (in the
schema itself) as "Overridden by the real VerificationConfig
graph-execution state, never trusted from the model's own claim" —
confirmed live: `run_arch_review()` reads
`final_state["verification"].get("import_graph_ran", False)`, NOT
`raw.get("import_graph_ran")`, so an LLM claiming `import_graph_ran:
true` without actually having called `import_graph` cannot forge
verification — already correct, no fix needed there.

One real finding, same class and shape as sibling tool #180's
`submit_ai_result`: **dead-code accumulator, never actually read.**
`ar_submit`'s original body did `arch_result.update(inp)`, and the
factory separately exported `handlers["_arch_result"] = arch_result`
— but grepping the entire production codebase found zero real
readers. The tool's real, functioning result-capture mechanism lives
entirely in `app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`run_arch_review()`'s own `raw = final_state["result"]` line, which
is what real production code actually consumes.

Fixed by removing the dead `arch_result` dict and `_arch_result`
export entirely — `submit_arch_review_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before, with zero behavior change to the
tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_ARCH_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_arch_review",
    "description": "Submit architecture review result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "structure_summary": {"type": "string"},
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                        },
                        "description": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "file:line — description entries from this run's real tool output",
                        },
                    },
                    "required": ["severity", "description", "evidence"],
                },
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "blast_radius": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
            "import_graph_ran": {
                "type": "boolean",
                "description": "Overridden by the real VerificationConfig graph-execution state, never trusted from the model's own claim — see run_arch_review()'s verification handling.",
            },
        },
        "required": [
            "structure_summary",
            "risks",
            "recommendations",
            "import_graph_ran",
        ],
    },
}


def submit_arch_review_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Architecture review submitted"
