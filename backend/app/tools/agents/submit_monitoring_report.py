"""submit_monitoring_report tool — tool_enhance.md productionization
pass, tool #189 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_monitoring_report
Old path: app/agents/tools.py (`_SUBMIT_MONITORING_REPORT_TOOL` schema
    dict, `mon_submit` inside `make_monitoring_agent_handlers()` — the
    one real implementation).
New path: app/tools/agents/submit_monitoring_report.py (this file) —
    `SUBMIT_MONITORING_REPORT_TOOL`, `submit_monitoring_report_handler`.
Affected agents: exactly 1 per tool_inventory.json — `monitoring_agent`
    (`app/agents/monitoring_agent.py`, via `run_monitoring_agent()`).
    Deliberately NOT in `CHAT_TOOLS` — confirmed via `CHAT_TOOLS`
    membership check — same correct-and-intentional absence already
    established for sibling tools #66/#180-#186/#188. Also note:
    `monitoring_agent.py`'s own `SCAN_TOOLS` (the autonomous
    scan-loop variant) deliberately EXCLUDES this tool in favor of
    `submit_enhancement_request` (a pre-existing, intentional design
    documented in that module's own AUDIT_Q_BATCH07 comment) — that
    swap is untouched here, out of scope for this tool's turn.
Affected modules: app/agents/tools.py (`mon_submit` delegates to the
    shared handler; the local `monitoring_result` dict accumulator and
    `handlers["_monitoring_result"]` export are removed — see
    finding). `make_monitoring_agent_handlers()`'s other handlers
    (`cpu_usage`, `memory_usage`, `disk_usage`, `health_check`,
    `task_progress`, `read_logs`) are each their own separately-
    productionized tool (several already GREEN_FLAGGED — see the
    tool_enhance.md comments still attached to them in tools.py) —
    deliberately untouched here, out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_monitoring_report" ToolManifestEntry is pure metadata,
    keyed by tool NAME not file path.
Affected tests: `tests/test_day2_agents.py` (the class covering
    `make_monitoring_agent_handlers`) asserted directly on the
    now-removed `h["_monitoring_result"]` dict (an internal
    implementation detail, not real production behavior — see
    finding). Updated to assert on the handler's real return value
    instead, preserving the test's actual intent (verify a real
    submission succeeds) without relying on dead internal state.
    `tests/test_audit_q_batch07_guardian_human_interaction.py` only
    asserts `submit_monitoring_report` is absent from `SCAN_TOOLS` —
    unaffected. New tests added: see
    tests/test_submit_monitoring_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_monitoring_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`status` is an enum,
`metrics`/`issues`/`recommendations` are free-form structured data —
the agent's real metric collection already happened via its own
separately gated `cpu_usage`/`memory_usage`/`disk_usage`/`health_check`
handlers before this tool is ever called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188: **dead-code accumulator, never actually read.**
`mon_submit`'s original body did `monitoring_result.update(inp)`, and
the factory separately exported `handlers["_monitoring_result"] =
monitoring_result` — but grepping the entire production codebase
found zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `run_monitoring_agent()`'s own `raw = final_state["result"]`
line, which is what real production code actually consumes.

Fixed by removing the dead `monitoring_result` dict and
`_monitoring_result` export entirely — `submit_monitoring_report_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Monitoring report
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_MONITORING_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_monitoring_report",
    "description": "Submit system monitoring report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["healthy", "warning", "critical"]},
            "metrics": {"type": "object"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "metrics"],
    },
}


def submit_monitoring_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Monitoring report submitted"
