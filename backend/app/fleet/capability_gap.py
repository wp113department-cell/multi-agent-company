"""Capability Gap Detection — AUDIT_Q_BATCH15 §76/§106/§108/§109/§116
gap-closure (2026-08-11).

"Capability gap detection from repeated failed/blocked requests" was
PARTIAL: agent_advisor (app/agents/agent_advisor.py) reviews whether "the
right agent(s) ran" from raw task_history_query/audit_log_read tool output —
real data, but orchestration-correctness review, not a dedicated mechanism
that clusters repeated failures by agent/capability. This module is that
dedicated mechanism: a deterministic (no LLM judgment involved) aggregation
over real AgentRun rows — the same table api/registry.py's success_rate
computation and agent_registry.compute_live_success_rate already treat as
ground truth — grouped by agent_type, counting real status='failed' rows and
surfacing their real, stored `error` text (never fabricated or paraphrased).

Exposed as a real tool (capability_gap_scan, app/agents/tools.py) so
agent_advisor's SCAN phase reviews a real computed cluster report instead of
trying to eyeball clustering from a flat task list — the actual gap the
audit identified, not just "more data for the LLM to maybe notice."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class CapabilityGapCluster:
    agent_name: str
    failure_count: int
    total_count: int
    failure_rate: float
    # Up to 5 distinct, real, truncated error strings from this agent's own
    # failed AgentRun rows — never a summarized/invented description.
    sample_errors: list[str] = field(default_factory=list)


def detect_capability_gaps(
    runs: list[Any],
    min_failures: int,
    min_failure_rate: float,
) -> list[CapabilityGapCluster]:
    """Pure function: real AgentRun-like rows in, real clusters out. Each
    row must expose .agent_type, .status, .error (AgentRun's own columns —
    see app/db/models.py). Only terminal runs (status in
    {"completed", "failed"}) count toward total_count; a still-"running" row
    is neither a success nor a failure yet and would silently deflate the
    real failure_rate if counted as a denominator entry.

    A cluster is only returned when BOTH min_failures AND min_failure_rate
    are met — a low-volume agent with 2 failures out of 2 runs is a real
    signal (100% failure rate) but 2 failures out of 200 healthy runs from a
    reliable agent is very likely noise, not a capability gap. Requiring
    both bounds avoids flagging either extreme in isolation.
    """
    by_agent: dict[str, list[Any]] = {}
    for r in runs:
        by_agent.setdefault(r.agent_type, []).append(r)

    clusters: list[CapabilityGapCluster] = []
    for agent_name, agent_runs in by_agent.items():
        terminal = [r for r in agent_runs if r.status in ("completed", "failed")]
        total = len(terminal)
        if total == 0:
            continue
        failed = [r for r in terminal if r.status == "failed"]
        if len(failed) < min_failures:
            continue
        rate = len(failed) / total
        if rate < min_failure_rate:
            continue

        seen: list[str] = []
        for r in failed:
            if not r.error:
                continue
            snippet = str(r.error).strip()[:200]
            if snippet and snippet not in seen:
                seen.append(snippet)
            if len(seen) >= 5:
                break

        clusters.append(
            CapabilityGapCluster(
                agent_name=agent_name,
                failure_count=len(failed),
                total_count=total,
                failure_rate=round(rate, 4),
                sample_errors=seen,
            )
        )

    clusters.sort(key=lambda c: (c.failure_count, c.failure_rate), reverse=True)
    return clusters


async def scan_capability_gaps(
    db: Any,
    window_days: int = 14,
    min_failures: int = 3,
    min_failure_rate: float = 0.3,
) -> list[CapabilityGapCluster]:
    """Query real AgentRun rows from the last window_days and detect
    clusters. Defaults (3 failures, 30% failure rate, 14-day window) are
    conservative enough not to flag a single bad-luck run or a brand-new
    agent's first couple of failures, while still catching a genuinely
    struggling capability within about two weeks of real usage."""
    from sqlalchemy import select

    from app.db.models import AgentRun

    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    result = await db.execute(select(AgentRun).where(AgentRun.started_at >= since))
    runs = list(result.scalars().all())
    return detect_capability_gaps(runs, min_failures, min_failure_rate)


def format_capability_gap_report(clusters: list[CapabilityGapCluster]) -> str:
    """Render clusters as the structured text agent_advisor's
    capability_gap_scan tool returns — real numbers, real error snippets,
    never a fabricated narrative."""
    if not clusters:
        return "No capability gaps detected: no agent exceeded the failure-rate/count thresholds in the scan window."

    lines = ["Capability gap clusters (real AgentRun data, most severe first):\n"]
    for c in clusters:
        lines.append(
            f"- agent={c.agent_name}: {c.failure_count}/{c.total_count} runs "
            f"failed ({c.failure_rate:.0%}) in the scan window"
        )
        for err in c.sample_errors:
            lines.append(f"    error: {err}")
    return "\n".join(lines)
