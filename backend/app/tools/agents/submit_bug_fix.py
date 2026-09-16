"""submit_bug_fix tool — tool_enhance.md productionization pass, tool
#211 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_bug_fix
Old path: app/agents/tools.py (`_SUBMIT_BUG_FIX_TOOL` schema dict,
    `bf_submit` inside `make_bug_fix_handlers()` — the one real
    implementation).
New path: app/tools/agents/submit_bug_fix.py (this file) —
    `SUBMIT_BUG_FIX_TOOL`, `submit_bug_fix_handler`.
Affected agents: exactly 1 real agent per `BUG_FIX_TOOLS` (the tools
    list actually passed to `run_agent_graph` for `bug_fix`) —
    `bug_fix` (`app/agents/bug_fix.py`). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check — same
    correct-and-intentional absence already established for sibling
    tools #66/#180-#186/#188-#192/#194/#196-#201.
Affected modules: app/agents/tools.py (`bf_submit` delegates to the
    shared handler; the local `bug_fix_result` dict accumulator and
    `handlers["_bug_fix_result"]` export are removed — see finding
    #1); app/agents/bug_fix.py (`AGENT_CONTRACT["allowed_tools"]`
    corrected — see finding #2).
Affected registries: `app/fleet/capability_registry.py`'s
    `bug_fix` `AgentCapability` entry is built directly from
    `AGENT_CONTRACT["allowed_tools"]` at `_register()` time — fixing
    finding #2 also corrects what this tool declares to the fleet's
    capability registry (used by `delegate_to_agent`'s target-agent
    lookups, dashboards, and `filter_runtime_tools`'s high-risk-tool
    gate). `submit_bug_fix` itself is not high-risk, so this had no
    observable runtime effect via `filter_runtime_tools` before the
    fix — but the registry's *declared* capability was still real,
    externally-visible, wrong metadata about what this agent can
    actually do.
Affected tests: `tests/test_day2_agents.py::TestBugFixHandlers::
    test_submit_stores_result` asserted directly on the now-removed
    `h["_bug_fix_result"]` dict (an internal implementation detail,
    not real production behavior — see finding #1). Updated to assert
    on the handler's real return value instead. New tests added: see
    tests/test_submit_bug_fix_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_bug_fix.md.
---------------------------------------------------------------------------

Two real findings.

1. **Dead-code accumulator, never actually read — same class as
   sibling tools #180-#186/#188-#192/#194/#196-#201.** `bf_submit`'s
   original body did `bug_fix_result.update(inp)`, and the factory
   separately exported `handlers["_bug_fix_result"] = bug_fix_result`
   — but grepping the entire production codebase found zero real
   readers. The tool's real, functioning result-capture mechanism
   lives entirely in `app/agents/base_graph.py`'s generic
   tool-execution node, confirmed by `bug_fix.py`'s own `raw =
   final_state["result"]` line.
2. **`AGENT_CONTRACT["allowed_tools"]` declares a tool `bug_fix`
   cannot actually call, and omits the one it actually does.** The
   contract lists `"submit_patch"` — but `make_bug_fix_handlers()` has
   no `submit_patch` handler at all (grepped: only `submit_bug_fix` /
   `bf_submit` exists), and the REAL runtime tool list actually passed
   to `run_agent_graph()` (`BUG_FIX_TOOLS`, imported and used directly
   by `bug_fix.py::run_bug_fix`) correctly includes
   `_SUBMIT_BUG_FIX_TOOL`, not a `submit_patch` entry. The agent's own
   role-prompt text (`"6. Call submit_bug_fix with root_cause,
   fix_summary, files_changed, tests_passed."`) already correctly
   names the real tool — only the separate, secondary
   `AGENT_CONTRACT["allowed_tools"]` metadata (used for fleet
   capability-registry registration, not the actual LLM tool list) was
   stale. Confirmed via a live capability-registry lookup that the
   registered `AgentCapability.tools` for `"bug_fix"` mirrored this
   same stale `"submit_patch"` entry. `submit_bug_fix` is not a
   high-risk tool, so `filter_runtime_tools()`'s declared-tools gate
   was never actually triggered by this mismatch — no functional
   runtime breakage, but real, externally-visible wrong metadata about
   this agent's actual capabilities.

Fixed by removing the dead `bug_fix_result` dict and
`_bug_fix_result` export entirely — `submit_bug_fix_handler()` now
does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Bug fix
submitted"`), closing finding #1. `AGENT_CONTRACT["allowed_tools"]` in
`app/agents/bug_fix.py` now lists `"submit_bug_fix"` in place of the
stale `"submit_patch"`, closing finding #2.
"""

from __future__ import annotations

from typing import Any

SUBMIT_BUG_FIX_TOOL: dict[str, Any] = {
    "name": "submit_bug_fix",
    "description": "Submit the bug fix: root cause analysis and files modified.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {"type": "string"},
            "fix_summary": {"type": "string"},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "tests_passed": {"type": "boolean"},
        },
        "required": ["root_cause", "fix_summary", "files_changed"],
    },
}


def submit_bug_fix_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Bug fix submitted"
