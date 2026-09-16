"""capability_gap_scan tool — tool_enhance.md productionization pass,
tool #210 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: capability_gap_scan
Old path: app/agents/tools.py (`_CAPABILITY_GAP_SCAN_TOOL` schema
    dict, module-level `capability_gap_scan()` function — the one
    real implementation, a thin sync-to-async bridge over the real
    logic in `app.fleet.capability_gap`).
New path: app/tools/agents/capability_gap_scan.py (this file) —
    `CAPABILITY_GAP_SCAN_TOOL`, `capability_gap_scan_handler`.
Affected agents: exactly 1 real caller — `agent_advisor`
    (`app/agents/agent_advisor.py::run_agent_advisor_scan`, via its
    own `SCAN_TOOLS` list, genuinely wired into the real periodic
    fleet scan loop in `app/main.py`). `tool_inventory.json` reports
    `agent_count: 0` for this tool — a heuristic false negative: it is
    NOT in `agent_advisor`'s general `AGENT_CONTRACT["allowed_tools"]`
    (that list is for a *different* invocation path this agent
    doesn't currently use for scanning), but IS in the separate,
    scan-specific `SCAN_TOOLS` list `run_agent_advisor_scan()` actually
    passes to `run_agent_graph()` — the same intentional
    general-contract-vs-scan-tool-list split already established for
    `monitoring_agent.py` (tool #189), `quality_auditor.py`, and
    `dependency_security_agent.py`. Verified genuinely reachable, not
    dead code, by reading `run_agent_advisor_scan()`'s own
    `tools=SCAN_TOOLS + [RECORD_LEARNING_TOOL]` line and confirming
    `app/main.py` registers `("agent_advisor", "app.agents.agent_advisor",
    "run_agent_advisor_scan")` in its real scan-loop table.
Affected modules: app/agents/tools.py (re-exports the schema and
    handler under their old names for backward compatibility);
    app/agents/agent_advisor.py (imports directly from this new
    module instead of via `app.agents.tools`).
Affected registries: none — app/fleet/tool_manifest.py's
    "capability_gap_scan" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_batch15_capability_gap.py` — 8 tests,
    already exercises the real underlying `app.fleet.capability_gap`
    pure functions (`detect_capability_gaps`,
    `format_capability_gap_report`) directly; `tool_inventory.json`'s
    "0 test files" for this specific tool name is another heuristic
    false negative (the test file doesn't call the function by its
    exact tool name — same class of false negative already documented
    for tools #3/#7). Re-run and confirmed passing unchanged, no fix
    needed. New tests added: see
    tests/test_capability_gap_scan_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/capability_gap_scan.md.
---------------------------------------------------------------------------

No injection surface: `window_days`/`min_failures`/`min_failure_rate`
are used only as bind parameters to a real, fully-parameterized
SQLAlchemy ORM query (`select(AgentRun).where(AgentRun.started_at >=
since)`) inside `app.fleet.capability_gap.scan_capability_gaps()` — no
raw SQL string interpolation anywhere.

One real finding, same class already documented for tools
#70/#72/#76/#127/#130/#135/#176: **uncaught crash on malformed
numeric input.** The original body did `window_days =
int(inp.get("window_days", 14))` (and the `min_failures`/
`min_failure_rate` coercions) OUTSIDE the function's own
`try`/`except` — that `try` only wrapped `asyncio.run(_run())`. Proved
live: `capability_gap_scan_handler({"window_days": "not-a-number"})`
raised an uncaught `ValueError` that escaped the handler entirely,
rather than returning a clean `[ERROR]` string like every other
failure path in this same function already does. Mitigated but not
eliminated by the agent framework's own outer generic exception
handling in `base_graph.py`'s tool-execution node, but a real,
genuine gap in this tool's own error-handling contract. Fixed by
moving the numeric coercions inside their own `try`/`except
(TypeError, ValueError)`, returning `"[ERROR] capability_gap_scan:
invalid numeric argument: ..."` instead of raising.

Deterministic, non-LLM-judgment clustering (`detect_capability_gaps()`)
already has 8 real, substantial existing tests covering threshold
logic, still-running-run exclusion, and severity sorting. Genuinely
wired into the real fleet scan loop (see migration report above) —
not orphaned/dead code despite the `agent_count: 0` inventory
artifact.

Modularized for structural consistency with the rest of this
initiative — the thin sync-to-async bridge (`asyncio.run()` +
`new_isolated_async_engine()`, matching every other DB-backed sync
tool handler in this codebase per this module's own
`feedback_asyncio_isolated_engine` precedent) is otherwise unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

CAPABILITY_GAP_SCAN_TOOL: dict[str, Any] = {
    "name": "capability_gap_scan",
    "description": (
        "AUDIT_Q_BATCH15 §76 gap-closure — deterministically cluster real AgentRun "
        "history by agent_type and surface any agent whose real failure count/rate "
        "over the scan window crosses a real threshold, with real sample error text "
        "from those failed runs. Use this instead of trying to eyeball a capability "
        "gap from raw task_history_query output — the clustering itself is already "
        "computed for you here, not something to infer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "window_days": {
                "type": "integer",
                "description": "Lookback window in days (default 14).",
            },
            "min_failures": {
                "type": "integer",
                "description": "Minimum failed-run count for an agent to be reported (default 3).",
            },
            "min_failure_rate": {
                "type": "number",
                "description": "Minimum failure rate (0.0-1.0) for an agent to be reported (default 0.3).",
            },
        },
        "required": [],
    },
}


def capability_gap_scan_handler(inp: dict[str, Any]) -> str:
    """Sync tool handler — bridges to the async DB query the same way every
    other DB-backed sync tool handler in this module does (new isolated
    engine + asyncio.run(), never the shared app.db.session engine — see
    feedback_asyncio_isolated_engine)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine
    from app.fleet.capability_gap import (
        format_capability_gap_report,
        scan_capability_gaps,
    )

    try:
        window_days = int(inp.get("window_days", 14))
        min_failures = int(inp.get("min_failures", 3))
        min_failure_rate = float(inp.get("min_failure_rate", 0.3))
    except (TypeError, ValueError) as exc:
        return f"[ERROR] capability_gap_scan: invalid numeric argument: {exc}"

    async def _run() -> str:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                clusters = await scan_capability_gaps(
                    db,
                    window_days=window_days,
                    min_failures=min_failures,
                    min_failure_rate=min_failure_rate,
                )
                return format_capability_gap_report(clusters)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        return f"[ERROR] capability_gap_scan failed: {exc}"
