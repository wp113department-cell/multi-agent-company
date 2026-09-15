"""submit_ai_result tool — tool_enhance.md productionization pass,
tool #180 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_ai_result
Old path: app/agents/tools.py (`_SUBMIT_AI_RESULT_TOOL` schema dict,
    `ae_submit` inside `make_ai_engineer_handlers()` — the one real
    implementation).
New path: app/tools/agents/submit_ai_result.py (this file) —
    `SUBMIT_AI_RESULT_TOOL`, `submit_ai_result_handler`.
Affected agents: exactly 1 per tool_inventory.json —
    `ai_engineer` (`app/agents/ai_engineer.py`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — this
    is a one-shot-agent submission tool with no interactive-chat use
    case, same correct-and-intentional absence already established
    for sibling tool #66's `record_learning`.
Affected modules: app/agents/tools.py (`ae_submit` delegates to the
    shared handler; the local `ai_result` dict accumulator and
    `handlers["_ai_result"]` export are removed — see finding).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_ai_result" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via `make_ai_engineer_handlers(...)`. New
    tests added: see tests/test_submit_ai_result_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_ai_result.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema — `summary`,
`files_created`, `eval_results`, `next_steps` are free-form
structured data with zero injection surface. Not in `CHAT_TOOLS`, so
the "advertised but never dispatched" class does not apply either.

One real finding: **dead-code accumulator, never actually read.**
`ae_submit`'s original body did `ai_result.update(inp)` and the
factory separately exported `handlers["_ai_result"] = ai_result` —
but grepping the entire codebase found ZERO real readers of
`handlers["_ai_result"]` anywhere. The tool's real, functioning
result-capture mechanism lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node: any
`tool_name.startswith("submit_")` call sets `submitted = True` and
captures `raw_result = dict(tu_input)` — the tool call's own LLM-
supplied ARGUMENTS — directly into `state["result"]`, completely
independent of what the handler itself does internally or returns.
`ae_submit`'s local `ai_result` dict was therefore genuinely
vestigial: written to, exported, but never consumed by anything —
confirmed by reading `run_agent_graph`'s Groq-bypass path too (a
SEPARATE, TEMPORARY generic `submit_*` wrapper at base_graph.py's own
`_make_wrapper`, which populates its own `tool_handlers["_result"]`
key directly from `tu_input`, again never touching `_ai_result`).
This exact same dead-accumulator shape recurs across essentially
every sibling `*_submit` handler in `app/agents/tools.py` (`ar_submit`,
`ba_submit`, `ci_submit`, etc. — confirmed via grep) since they all
follow the same historical pattern; each will be addressed on its own
turn in this initiative (tools #181/#182/#183/... for the ones still
pending) rather than fixed in bulk here, to keep each tool's own
audit and verification independently real.

Fixed by removing the dead `ai_result` dict and `_ai_result` export
entirely — `submit_ai_result_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before, with zero behavior change to the
tool's real end-to-end effect (verified by re-running the real
`ai_engineer` agent's own existing test coverage unchanged).
"""

from __future__ import annotations

from typing import Any

SUBMIT_AI_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_ai_result",
    "description": "Submit AI/ML engineering task results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "files_created": {"type": "array", "items": {"type": "string"}},
            "eval_results": {"type": "object"},
            "next_steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}


def submit_ai_result_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "AI engineering result submitted"
