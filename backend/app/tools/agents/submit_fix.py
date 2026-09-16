"""submit_fix tool — tool_enhance.md productionization pass, tool
#214 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_fix
Old path: FOUR separate, independently-maintained implementations,
    one inline in each of `app/agents/agent_performance_reviewer.py`,
    `app/agents/knowledge_curator.py`, `app/agents/agent_debugger.py`,
    and `app/agents/quality_auditor.py` — each its own module-level
    `_SUBMIT_FIX_TOOL_SPEC` schema dict plus its own local `submit_h`
    closure inside that agent's `run_*_apply()` function.
New path: app/tools/agents/submit_fix.py (this file) —
    `SUBMIT_FIX_TOOL`, `submit_fix_handler`. All 4 real call sites now
    import and use this one shared pair instead of maintaining their
    own copies.
Affected agents: exactly 4, confirmed via direct grep of every real
    `_SUBMIT_FIX_TOOL_SPEC`/`submit_h`/`handlers["submit_fix"]`
    definition — `agent_performance_reviewer`, `knowledge_curator`,
    `agent_debugger`, `quality_auditor` — matching
    `tool_inventory.json`'s `agent_count: 4` exactly. Deliberately NOT
    in `CHAT_TOOLS` — confirmed via membership check; this is an
    APPLY-phase-only, human-approval-gated "I'm done" signal, not
    exposed to interactive chat.
Affected modules: all 4 agent files now import `SUBMIT_FIX_TOOL as
    _SUBMIT_FIX_TOOL_SPEC` and `submit_fix_handler` in place of their
    own local definitions.
Affected registries: none — app/fleet/tool_manifest.py's "submit_fix"
    entry (if present) is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via `handlers["submit_fix"](...)` on one of the
    4 real handler factories, and the handler's return value
    (`"done"`) and schema shape are both preserved verbatim. New tests
    added: see tests/test_submit_fix_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_fix.md.
---------------------------------------------------------------------------

No security vulnerability and no functional bug found — the real
finding here is DUPLICATION, not a defect. All 4 real implementations
were already 100% functionally identical: `def submit_h(inp): return
"done"`, byte-for-byte the same in every file, and all 4 schemas share
the identical `{summary: string}` shape (`required: ["summary"]`) —
differing only in cosmetic `description` text ("Signal the fix is
complete and committed." / "Signal the curation action is complete."
/ "Signal the fix is complete, tested, and committed." twice). No
input validation, state, or side effect exists in any of the 4 to
diverge on.

This is NOT a dead-accumulator finding (the class documented for
tools #180-#186/#188-#192/#194/#196-#201/#211): there is no local dict
to go stale here at all. The real, functioning result-capture
mechanism is `app/agents/base_graph.py`'s generic `submit_*` handling
(`state["result"] = dict(tu_input)`) exactly as for those siblings —
confirmed directly by reading each of the 4 real callers'
`raw = final_state.get("result", {})` line, which is what genuinely
carries the LLM's `summary` field forward into the returned
`AgentResult.raw`. `submit_h`'s own hardcoded `"done"` return is only
the confirmation text shown back to the LLM, same pattern as every
other tool in this initiative's `submit_*` family.

Unified purely for consistency and to eliminate duplicate code,
matching the precedent already established for tool #85's
`submit_docs` (4 implementations, unified into one shared
`make_submit_docs_handler`) — standardized on one description
("Signal the approved change (fix or knowledge-curation action) is
complete.") that accurately covers all 4 real contexts, since none of
the 4 original description variants carried any behavior-affecting
meaning.
"""

from __future__ import annotations

from typing import Any

SUBMIT_FIX_TOOL: dict[str, Any] = {
    "name": "submit_fix",
    "description": "Signal the approved change (fix or knowledge-curation action) is complete.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}


def submit_fix_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "done"
