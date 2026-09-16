"""submit_docker_report tool — tool_enhance.md productionization pass,
tool #186 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_docker_report
Old path: app/agents/tools.py (`_SUBMIT_DOCKER_REPORT_TOOL` schema
    dict, `dk_submit` inside `make_docker_agent_handlers()` — the one
    real implementation).
New path: app/tools/agents/submit_docker_report.py (this file) —
    `SUBMIT_DOCKER_REPORT_TOOL`, `submit_docker_report_handler`.
Affected agents: exactly 1 per tool_inventory.json — `docker_agent`
    (`app/agents/docker_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
    confirmed via `CHAT_TOOLS` membership check — same correct-and-
    intentional absence already established for sibling tools
    #66/#180/#181/#182/#183/#184/#185.
Affected modules: app/agents/tools.py (`dk_submit` delegates to the
    shared handler; the local `docker_result` dict accumulator and
    `handlers["_docker_result"]` export are removed — see finding).
    `make_docker_agent_handlers()`'s other handlers (`docker_ps`,
    `docker_logs`, `docker_exec`, `docker_compose`, `docker_build`,
    `docker_restart`, `diagnose_deployment_failure`, `write_file`) are
    each their own separately-productionized tool (several already
    GREEN_FLAGGED — see the tool_enhance.md comments still attached to
    them in tools.py) — deliberately untouched here, out of scope for
    this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_docker_report" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestDockerAgentHandlers::
    test_submit_docker_report` asserted directly on the now-removed
    `h["_docker_result"]` dict (an internal implementation detail, not
    real production behavior — see finding). Updated to assert on the
    handler's real return value instead, preserving the test's actual
    intent (verify a real submission succeeds) without relying on
    dead internal state. New tests added: see
    tests/test_submit_docker_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_docker_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`action`, `outcome`,
`files_written` are all free-form strings/structured data — any real
docker action already happened via the agent's own separately gated
docker_* handlers before this tool is ever called) — no injection
surface.

One real finding, same class and shape as sibling tools
#180/#181/#182/#183/#184/#185: **dead-code accumulator, never actually
read.** `dk_submit`'s original body did `docker_result.update(inp)`,
and the factory separately exported `handlers["_docker_result"] =
docker_result` — but grepping the entire production codebase found
zero real readers. The tool's real, functioning result-capture
mechanism lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `docker_agent.py`'s own `raw = final_state["result"]` line,
which is what real production code actually consumes.

Fixed by removing the dead `docker_result` dict and
`_docker_result` export entirely — `submit_docker_report_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Docker report
submitted"`), with zero behavior change to the tool's real end-to-end
effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_DOCKER_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_docker_report",
    "description": "Submit Docker agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "outcome": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "outcome"],
    },
}


def submit_docker_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "Docker report submitted"
