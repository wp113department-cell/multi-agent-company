"""submit_result tool — tool_enhance.md productionization pass, tool
#194 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_result
Old path: app/agents/tools.py (`_SUBMIT_RESULT_TOOL` schema dict) with
    TWO implementations that were NOT functionally identical (unlike
    every prior "duplicate implementation" finding in this
    initiative, e.g. tool #85's submit_docs):
      1. `app/agents/chat_agent.py::ChatAgent._execute_tool`'s own
         inline `if tool_name == "submit_result": return f"Task
         complete: {status}\n{summary}"` branch — the REAL, ONLY
         production code path, since `submit_result` is exclusively a
         `CHAT_TOOLS` entry (confirmed: `CHAT_TOOLS` membership count
         is 1) and `_execute_tool` is `ChatAgent`'s own
         self-contained if/elif dispatcher — it never calls
         `make_chat_handlers()` or any handlers dict at all (grepped:
         zero real calls, only comments referencing it — several of
         those comments, at chat_agent.py lines ~2121/3493/3633,
         already independently describe OTHER tools' "currently
         unreachable make_chat_handlers() implementation", the exact
         same class of finding this tool has).
      2. `make_chat_handlers()`'s own `submit_result` closure (`
         chat_result.update(inp); return f"Result submitted:
         {status}"`, with `handlers["_chat_result"] = chat_result`) —
         GENUINELY UNREACHABLE. Confirmed via two independent checks:
         (a) `chat_agent.py` never calls `make_chat_handlers()` (grep,
         above); (b) grepped all 37 other agent files that DO call
         `make_chat_handlers()` as their base (`accessibility_agent`,
         `agentic_ai_architect`, `compliance_agent`, and 34 more) —
         none of them include `"submit_result"` in their own tool
         list; each defines and exposes its own distinctly-named
         `submit_<agent>` tool instead. `_chat_result` has zero real
         readers anywhere in the codebase.
New path: app/tools/agents/submit_result.py (this file) —
    `SUBMIT_RESULT_TOOL`, `submit_result_handler`. The REAL,
    production-observed behavior (implementation 1 above) is the one
    preserved verbatim; implementation 2's unreachable closure and its
    dead `chat_result`/`_chat_result` state are removed entirely.
Affected agents: exactly 1 per tool_inventory.json — `chat_agent`
    (interactive chat session only).
Affected modules: app/agents/chat_agent.py (`_execute_tool`'s
    `submit_result` branch now delegates to the shared handler,
    verbatim same output); app/agents/tools.py (`make_chat_handlers()`'s
    now-removed `submit_result`/`chat_result`/`_chat_result` — the
    `"submit_result"` key is still populated in the returned handlers
    dict, now pointing at this file's shared, REAL-behavior handler,
    so no functionality is lost for any future caller that might
    someday reach it via that dict).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_result" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: the 18 test files `tool_inventory.json` lists against
    this tool (`test_batch18_citation_verification.py`,
    `test_cluster_o_repo_scoped_memory_isolation.py`,
    `test_confidence_gated_control_flow.py`, `test_day0_capabilities.py`,
    `test_day0_groq_integration.py`, `test_dynamic_tool_selection.py`,
    `test_gap16_limitation_taxonomy.py`,
    `test_gap20_execute_tools_batch_with_critique.py`,
    `test_gap_stage15_context_condense.py`,
    `test_gap_stage16_hard_constraint_clarification.py`,
    `test_hierarchy_chain.py`, `test_lesson_versioned_memory_wiring.py`,
    `test_metrics_wiring.py`, `test_phase35_self_critique.py`,
    `test_phase36_continuous_replanning.py`, `test_phase37_quality_gate.py`,
    `test_phase63_prompt_injection_defense.py`,
    `test_stage4_clustern_real_agent_run_heartbeat.py`) are ALL a
    false-positive from `tool_inventory.json`'s exact-string-match
    heuristic (the same class of false-positive already documented for
    tools #3/#7 in the opposite direction — there, a real test file
    was missed; here, 18 unrelated files are over-matched): every one
    of them uses `"submit_result"` purely as an arbitrary example tool
    NAME to test `app/agents/base_graph.py`'s own generic
    submit_*-prefixed graph mechanics (self-critique, replanning,
    quality gates, memory wiring, heartbeats, dynamic tool selection)
    — via inline dummy schemas and `lambda inp: "ok"` mock handlers,
    never importing `SUBMIT_RESULT_TOOL`/`make_chat_handlers` from
    `app.agents.tools` at all (verified by reading representative
    samples). None required a change. No existing test exercises the
    real chat_agent.py dispatch or make_chat_handlers()'s
    implementation of THIS specific tool at all — a genuine, closed
    coverage gap. New tests added: see
    tests/test_submit_result_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_result.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`summary`, `status` are
plain strings) — no injection surface.

Fixed by extracting the REAL, production-observed behavior
(`chat_agent.py`'s own dispatch) into this shared
`submit_result_handler()`, wiring `chat_agent.py`'s dispatch to call
it (byte-for-byte identical output), and replacing
`make_chat_handlers()`'s separate, unreachable, differently-worded
duplicate (and its dead `chat_result`/`_chat_result` state) with the
same shared, real-behavior handler.
"""

from __future__ import annotations

from typing import Any

SUBMIT_RESULT_TOOL: dict[str, Any] = {
    "name": "submit_result",
    "description": "Signal that the task is fully complete. Include a summary of what was done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What was accomplished, files changed, commands run",
            },
            "status": {
                "type": "string",
                "enum": ["done", "blocked"],
                "description": "done = complete, blocked = hit a wall and need help",
            },
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths of files created or modified",
            },
        },
        "required": ["summary", "status"],
    },
}


def submit_result_handler(inp: dict[str, Any]) -> str:
    """The real, production-observed behavior of this tool — extracted
    verbatim from app.agents.chat_agent.ChatAgent._execute_tool's own
    inline dispatch branch, the only implementation any real
    interactive chat session ever actually reaches."""
    return f"Task complete: {inp.get('status', 'done')}\n{inp.get('summary', '')}"
