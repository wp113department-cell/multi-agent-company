"""submit_enhancement_request tool — tool_enhance.md productionization
pass, tool #212 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_enhancement_request
Old path: app/agents/tools.py (`_SUBMIT_ENHANCEMENT_REQUEST_TOOL`
    schema dict, `make_submit_enhancement_request_handler()` factory
    — the one real implementation, shared by every real caller).
New path: app/tools/agents/submit_enhancement_request.py (this file)
    — `SUBMIT_ENHANCEMENT_REQUEST_TOOL`,
    `make_submit_enhancement_request_handler`.
Affected agents: `tool_inventory.json` reports `agent_count: 5`, but a
    direct grep of every real `make_submit_enhancement_request_handler(`
    call site found **8** real agents genuinely using this tool:
    `agent_advisor`, `agent_debugger`, `agent_performance_reviewer`,
    `architecture_reviewer` (its SCAN phase), `dependency_security_agent`,
    `knowledge_curator`, `monitoring_agent` (its SCAN phase), and
    `quality_auditor`. The inventory's "5" matches a stale count in a
    comment block still sitting in `tools.py` ("Shared by the 5
    self-improvement agents...") that predates 3 of these 8 real
    callers being added — a documentation lag, not a functional bug
    (each of the 8 real call sites was independently verified to
    genuinely import and wire the handler). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via `CHAT_TOOLS` membership check.
Affected modules: app/agents/tools.py re-exports the schema and
    factory under their old names — all 8 real consumer files
    continue to `from app.agents.tools import
    make_submit_enhancement_request_handler` unchanged, deliberately
    NOT individually edited to import from the new location, to
    minimize blast radius across 8 files for a tool this widely
    shared (their own `submit_*`/scan tools remain each agent's own
    future turn).
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_enhancement_request" entry (if present) is pure metadata,
    keyed by tool NAME not file path.
Affected tests: 7 existing test files already exercise this tool
    across its real call sites (`tests/test_batch18_enhancement_rollback.py`,
    `tests/test_batch18_enhancement_impact.py`,
    `tests/test_audit_q_batch07_guardian_human_interaction.py`,
    `tests/test_day9_fleet_agents.py`, `tests/test_gap49_dependency_scan.py`,
    `tests/test_submit_monitoring_report_hardening.py`,
    `tests/test_gap48_architecture_reviewer_scan.py` — 124 tests
    combined) — `tool_inventory.json`'s "3 test files" is another
    heuristic undercount. All re-run and confirmed passing unchanged,
    no fix needed. New tests added: see
    tests/test_submit_enhancement_request_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_enhancement_request.md.
---------------------------------------------------------------------------

No security vulnerability found after a thorough, direct audit of the
full real call graph (not assumed safe from its size or age):

- The DB write (`EnhancementRequest(...)`) goes through the SQLAlchemy
  ORM exclusively — no raw SQL string interpolation anywhere, no
  injection surface.
- The best-effort impact simulation
  (`app.fleet.enhancement_impact.simulate_enhancement_impact`)
  extracts `file:line` citations from the LLM-controlled
  `description`/`evidence` fields via a regex
  (`_FILE_LINE_CITATION_RE`) whose character class is restricted to
  `[A-Za-z0-9_./-]` — no regex metacharacters can appear in an
  extracted citation, ruling out a `grep -E` ReDoS/regex-injection via
  `_find_referencing_files()`'s `rf"\b{module_stem}\b"` pattern.
  Investigated directly: `_find_referencing_files()` also never opens
  a file at the extracted `rel_path` itself — it only derives a
  search TERM (the file's basename stem) and greps the *fixed*
  `repo_root` argument for it, so no worktree-escape file read is
  possible even with a traversal-shaped citation string.
- Both the DB write and the dashboard push are already wrapped in
  their own `try`/`except`, matching this initiative's established
  "clean `[ERROR]` string, never an uncaught exception" standard — a
  missing required `inp` key inside either block is already caught by
  its enclosing `except Exception`, verified by reading the exact
  exception boundaries (not assumed).
- `agent_name`/`trace_id`/`repo_path` are factory-time arguments each
  real caller hardcodes at construction time — never LLM-controlled.

One real, narrow finding: `make_submit_enhancement_request_handler()`'s
DB write used a LOCAL, less-completely-configured duplicate of the
canonical isolated-engine helper. `_new_isolated_db_engine()` (still
defined in `app/agents/tools.py`, used by 4 OTHER tools —
`memory_search`, `memory_curate_read`, `memory_curate_write`,
`git_commit_change` — each with its own future tool_enhance.md turn,
deliberately NOT touched here) creates its engine with only
`pool_pre_ping=True`, omitting the explicit `pool_size`/
`max_overflow`/`connect_args` the CANONICAL
`app.db.session.new_isolated_async_engine()` sets — the same
throwaway-engine helper `capability_gap_scan_handler()` (tool #210)
already uses. Per that canonical function's own docstring, omitting
these "silently fall[s] back to SQLAlchemy's smaller async defaults"
and skips whatever `connect_args` a real deployment's settings
require. Fixed for this tool specifically by switching to the
canonical helper; the other 4 call sites still using the local
duplicate are a separate, already-documented consolidation
opportunity for their own turns.
"""

from __future__ import annotations

from typing import Any

SUBMIT_ENHANCEMENT_REQUEST_TOOL: dict[str, Any] = {
    "name": "submit_enhancement_request",
    "description": (
        "File a proposed enhancement for human review on the Fleet Dashboard. "
        "Call this only when you have real evidence for a genuine issue or improvement — "
        "an empty scan with nothing to report is a normal, expected outcome, not a failure. "
        "This only creates a pending request; nothing changes on disk until a human approves it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title, plain language."},
            "description": {
                "type": "string",
                "description": "Full explanation in plain, non-technical-jargon language — this is what the human reads to decide approve/reject.",
            },
            "category": {
                "type": "string",
                "enum": [
                    "performance",
                    "bug",
                    "orchestration",
                    "knowledge",
                    "quality",
                    "security",
                ],
            },
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {
                "type": "object",
                "description": "file:line citations, metrics, or other evidence backing this claim.",
            },
        },
        "required": ["title", "description", "category", "priority"],
    },
}


def make_submit_enhancement_request_handler(
    agent_name: str, trace_id: str = "", repo_path: str = ""
) -> Any:
    """Factory shared by all 8 real self-improvement/scan agents (see
    this module's own docstring for the exact list — `agent_count: 5`
    in `tool_inventory.json` is a stale-comment undercount, not a real
    reachability gap)."""

    def submit_enhancement_request(inp: dict[str, Any]) -> str:
        import asyncio

        # AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — pre-change impact
        # simulation, computed here (SCAN/submission time, before ANY human
        # decision) so it's visible on the row the human actually reviews,
        # not bolted on after approval. Best-effort: a simulation failure
        # must never block filing the request itself — see this function's
        # own docstring for why an empty report is the honest fallback, not
        # a fabricated one.
        try:
            from app.fleet.enhancement_impact import simulate_enhancement_impact

            impact = simulate_enhancement_impact(
                repo_path, str(inp["description"]), dict(inp.get("evidence") or {})
            )
        except Exception:
            impact = None

        async def _write() -> int:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import EnhancementRequest
            from app.db.session import new_isolated_async_engine

            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(
                    engine, expire_on_commit=False
                )() as session:
                    # The scan loops run every few hours and the same finding persists until a human
                    # acts: without this every run filed another identical pending row (dashboard
                    # spam, and a human rejecting one still saw it return). Same agent + same title,
                    # still open — or rejected within the last 14 days — is not filed again.
                    from datetime import datetime, timedelta, timezone

                    from sqlalchemy import func, or_, select

                    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
                    existing = (
                        await session.execute(
                            select(EnhancementRequest.id, EnhancementRequest.status)
                            .where(
                                EnhancementRequest.agent_name == agent_name,
                                func.lower(func.trim(EnhancementRequest.title))
                                == str(inp["title"]).strip().lower(),
                                or_(
                                    EnhancementRequest.status.in_(
                                        ("pending", "in_progress")
                                    ),
                                    (EnhancementRequest.status == "rejected")
                                    & (EnhancementRequest.decided_at >= cutoff),
                                ),
                            )
                            .order_by(EnhancementRequest.id.desc())
                            .limit(1)
                        )
                    ).first()
                    if existing is not None:
                        return -int(existing[0])
                    row = EnhancementRequest(
                        agent_name=agent_name,
                        title=str(inp["title"]),
                        description=str(inp["description"]),
                        category=str(inp["category"]),
                        priority=str(inp["priority"]),
                        evidence=dict(inp.get("evidence") or {}),
                        status="pending",
                        trace_id=trace_id or None,
                        impact_simulation=impact,
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    return int(row.id)
            finally:
                await engine.dispose()

        try:
            req_id = asyncio.run(_write())
        except Exception as exc:
            return f"[ERROR] Could not file enhancement request: {exc}"

        if req_id < 0:
            return (
                f"Enhancement request #{-req_id} (same title) is already open or was "
                "rejected recently — not filed again."
            )
        try:
            from app.services.activity_stream import get_activity_registry

            stream = get_activity_registry().get_or_create("fleet-dashboard")
            stream.push(
                {
                    "type": "new_request",
                    "id": req_id,
                    "agentName": agent_name,
                    "title": str(inp["title"]),
                    "priority": str(inp["priority"]),
                    "category": str(inp["category"]),
                }
            )
        except Exception:
            pass  # dashboard notification is non-fatal — the row is already written

        return f"Enhancement request #{req_id} filed for human review."

    return submit_enhancement_request
