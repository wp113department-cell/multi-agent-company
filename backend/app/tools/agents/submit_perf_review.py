"""submit_perf_review tool — tool_enhance.md productionization pass,
tool #190 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_perf_review
Old path: app/agents/tools.py (`_SUBMIT_PERF_REVIEW_TOOL` schema dict,
    `pr_submit` inside `make_performance_reviewer_handlers()` — the
    one real implementation).
New path: app/tools/agents/submit_perf_review.py (this file) —
    `SUBMIT_PERF_REVIEW_TOOL`, `submit_perf_review_handler`.
Affected agents: exactly 1 per tool_inventory.json —
    `performance_reviewer` (`app/agents/performance_reviewer.py`).
    Deliberately NOT in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS`
    membership check — same correct-and-intentional absence already
    established for sibling tools #66/#180-#186/#188/#189.
Affected modules: app/agents/tools.py (`pr_submit` delegates to the
    shared handler; the local `perf_result` dict accumulator and
    `handlers["_perf_result"]` export are removed — see finding).
    `make_performance_reviewer_handlers()`'s other handlers
    (`find_sql`, `run_sql`, `explain_query`, `list_functions`) are
    each their own separately-productionized tool (several already
    GREEN_FLAGGED as tools #82/#91/#98) — deliberately untouched
    here, out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_perf_review" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day3_agents.py::TestPerformanceReviewerTools`
    and `::TestPerformanceReviewerHandlers` assert only tool-list
    membership and handler-key presence — neither references the
    internal `_perf_result` dict, so no fix was required there (same
    shape as tool #184). New tests added: see
    tests/test_submit_perf_review_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_perf_review.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`summary`, `findings`,
`severity`, `recommendations` are all free-form structured data — any
real query analysis already happened via the agent's own separately
gated `find_sql`/`run_sql`/`explain_query`/`list_functions` handlers
before this tool is ever called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188/#189: **dead-code accumulator, never actually read.**
`pr_submit`'s original body did `perf_result.update(inp)`, and the
factory separately exported `handlers["_perf_result"] = perf_result`
— but grepping the entire production codebase found zero real
readers. The tool's real, functioning result-capture mechanism lives
entirely in `app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`performance_reviewer.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `perf_result` dict and `_perf_result`
export entirely — `submit_perf_review_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before (`"Performance review submitted"`),
with zero behavior change to the tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_PERF_REVIEW_TOOL: dict[str, Any] = {
    "name": "submit_perf_review",
    "description": "Submit performance review findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "object"}},
            "severity": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}


def submit_perf_review_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Performance review submitted"
