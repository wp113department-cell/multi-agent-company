"""fleet_metrics_read tool — tool_enhance.md productionization pass,
tool #215 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: fleet_metrics_read
Old path: app/agents/tools.py (`_FLEET_METRICS_READ_TOOL` schema dict,
    module-level `fleet_metrics_read()` function — the one real
    implementation).
New path: app/tools/agents/fleet_metrics_read.py (this file) —
    `FLEET_METRICS_READ_TOOL`, `fleet_metrics_read_handler`.
Affected agents: exactly 3 real agents, confirmed via direct grep —
    `agent_advisor`, `agent_performance_reviewer`, `agent_debugger` —
    matching `tool_inventory.json`'s `agent_count: 3` exactly.
    Deliberately NOT in `CHAT_TOOLS` — confirmed via membership check.
Affected modules: app/agents/tools.py re-exports the schema and
    function under their old names — all 3 real consumer files
    continue `from app.agents.tools import fleet_metrics_read`
    unchanged.
Affected registries: none — app/fleet/tool_manifest.py's
    "fleet_metrics_read" entry (if present) is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day9_fleet_agents.py` (2 tests) and
    `tests/test_batch16_scheduler_and_metrics.py` already exercise
    this tool via real calls to `fleet_metrics_read()` (in-process, no
    DB) — neither passes a malformed `n`, so both re-run and confirmed
    passing unchanged, no fix needed there. New tests added: see
    tests/test_fleet_metrics_read_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/fleet_metrics_read.md.
---------------------------------------------------------------------------

No injection surface: this tool is entirely in-process (per the
comment block above its old location in tools.py — "SCAN phase
(autonomous, read-only): fleet_metrics_read, audit_log_read... —
in-process, no DB"), reading from `app.fleet.metrics`'s real
in-memory metrics collector — no SQL, no subprocess, no filesystem
access at all.

One real, SEVERE finding — a genuine, empirically-verified uncaught
crash, WORSE than the same class already documented for tools
#70/#72/#76/#127/#130/#135/#176/#210: this function had **zero**
`try`/`except` anywhere in its body (not even a misplaced one, unlike
tool #210's `capability_gap_scan`). `n = int(inp.get("n", 20))` was a
bare coercion with no guard at all. Proved live:
`fleet_metrics_read({"n": "not-a-number"})` raised a real, completely
uncaught `ValueError` that would propagate straight out of the tool
handler — mitigated but not eliminated by the agent framework's own
outer generic exception handling in `base_graph.py`'s tool-execution
node, but a real, genuine gap in this tool's own error-handling
contract, exactly the class this initiative has repeatedly found and
fixed elsewhere.

Fixed by wrapping the numeric coercion (`n`) in its own
`try`/`except (TypeError, ValueError)`, returning a clean
`"[ERROR] fleet_metrics_read: invalid numeric argument for n: ..."`
string instead of raising — matching every other tool's established
"clean [ERROR] string, never an uncaught exception" standard in this
codebase. All other behavior (per-agent metrics summary, fleet-wide
recent-runs listing, p50/p95 latency, average tool accuracy)
preserved verbatim.
"""

from __future__ import annotations

from typing import Any

FLEET_METRICS_READ_TOOL: dict[str, Any] = {
    "name": "fleet_metrics_read",
    "description": "Read real runtime performance data for an agent (or the whole fleet): recent runs, p50/p95 latency, average tool accuracy. Use this before claiming an agent is slow or unreliable — never guess.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Agent to inspect. Omit to see the most recent runs across all agents.",
            },
            "n": {
                "type": "integer",
                "description": "Max runs to consider (default 20).",
            },
        },
        "required": [],
    },
}


def fleet_metrics_read_handler(inp: dict[str, Any]) -> str:
    """Core fleet_metrics_read logic — real, in-process, no DB/no
    injection surface. `n` is now coerced inside its own try/except,
    closing this module's own documented uncaught-crash finding."""
    from app.fleet.metrics import get_metrics_collector

    agent_name = str(inp.get("agent_name", "")).strip()
    try:
        n = int(inp.get("n", 20))
    except (TypeError, ValueError) as exc:
        return f"[ERROR] fleet_metrics_read: invalid numeric argument for n: {exc}"

    collector = get_metrics_collector()

    if not agent_name:
        runs = collector.recent(n)
        if not runs:
            return "(no runs recorded yet)"
        lines = [
            f"{m.agent_name}: status={m.status} time={m.execution_time_ms:.0f}ms tokens_in={m.tokens_in} tokens_out={m.tokens_out}"
            for m in runs
        ]
        return "\n".join(lines)

    runs = collector.by_agent(agent_name, n)
    if not runs:
        return f"(no recorded runs for agent {agent_name!r})"
    p50 = collector.p50_latency_ms(agent_name)
    p95 = collector.p95_latency_ms(agent_name)
    accuracy = collector.avg_tool_accuracy(agent_name)
    failed = sum(1 for m in runs if m.status == "failed")
    lines = [
        f"agent: {agent_name}",
        f"runs considered: {len(runs)} (failed: {failed})",
        f"p50 latency: {p50:.0f}ms" if p50 is not None else "p50 latency: n/a",
        f"p95 latency: {p95:.0f}ms" if p95 is not None else "p95 latency: n/a",
        (
            f"avg tool accuracy: {accuracy:.2f}"
            if accuracy is not None
            else "avg tool accuracy: n/a"
        ),
    ]
    return "\n".join(lines)
