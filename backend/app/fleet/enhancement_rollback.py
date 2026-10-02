"""Automatic rollback-on-quality-decline — AUDIT_Q_BATCH18 §69 gap-closure
(2026-08-12).

"Autonomous Quality Improvement" (Safe Self-Improvement Lifecycle) was real
for 6 of 8 steps; step 8, "rollback if quality declines," already exists
and is genuinely automatic (no human-approval gate) — but only for PROMPT
versions (app.main._prompt_auto_rollback_loop, built on
prompt_registry.rollback() + regression_detector.check_fleet()). No
equivalent existed for EnhancementRequest-driven CODE commits (the
agent_performance_reviewer/agent_debugger/knowledge_curator/quality_auditor
APPLY phases) — an applied enhancement that measurably makes an agent
worse had no automatic corrective path at all, only a human noticing on
their own.

This module is that missing half, deliberately built on the SAME already-
proven pattern and the SAME risk posture (fully automatic — this codebase's
own existing precedent already treats "roll back an underperforming
self-improvement" as safe to do without a human approval gate, distinct
from the forward APPLY path which does require one) rather than inventing
a different, more conservative mechanism for what is architecturally the
same kind of decision. `git revert` (never reset/force-push) keeps this
safe and non-destructive — a revert is itself just another commit, fully
visible in history and itself revertible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def capture_commit_sha_if_verified(
    repo_path: str, final_state: Any, verification_key: str = "committed"
) -> str | None:
    """Real call site every EnhancementRequest APPLY function (agent_
    performance_reviewer.py, agent_debugger.py, knowledge_curator.py,
    quality_auditor.py) now uses right before building its return
    AgentResult: `EnhancementRequest.commit_sha` existed on the model but
    was never actually populated by any APPLY function (grepped: zero
    writers before this) — this is the one real place each of those 4
    functions independently arrived at needing this exact primitive, so
    it lives once here rather than duplicated 4 times. Never raises: a
    subprocess failure just means no sha (the row's commit_sha stays
    NULL, an honest "we don't know" rather than a fabricated value) —
    matching this codebase's own zero-hallucination convention.
    """
    if not final_state.get("verification", {}).get(verification_key):
        return None
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        logger.debug("Could not capture HEAD sha for %s", repo_path, exc_info=True)
    return None


async def compute_success_rate_window(
    db: Any, agent_type: str, start: datetime, end: datetime
) -> tuple[float | None, int]:
    """Real success_rate for `agent_type` computed ONLY from AgentRun rows
    whose started_at falls in [start, end) — the time-windowed sibling of
    app.fleet.agent_registry.compute_live_success_rate (which is
    intentionally all-time, for a different real caller: live routing
    score). Returns (None, 0) when there are zero runs in the window — the
    same "don't fabricate a rate from no data" convention
    compute_live_success_rate already established, just returning None
    instead of a fallback since there's no natural fallback for "before
    this specific change" / "after this specific change" windows.
    """
    from sqlalchemy import case, func, select

    from app.db.models import AgentRun

    # SQL aggregate over FINISHED runs. This used to load every row and count runs still
    # "running" as failures — and the post-change window always ends "now", so it always
    # contains in-flight runs: the comparison was biased toward "declined", and a decline
    # triggers an automatic, unattended `git revert` of the enhancement.
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(
                    func.sum(case((AgentRun.status == "completed", 1), else_=0)), 0
                ),
            ).where(
                AgentRun.agent_type == agent_type,
                AgentRun.started_at >= start,
                AgentRun.started_at < end,
                AgentRun.status != "running",
            )
        )
    ).one()
    total, successes = int(row[0]), int(row[1])
    if total == 0:
        return None, 0
    return successes / total, total


@dataclass
class QualityDeclineReport:
    request_id: int
    agent_name: str
    pre_success_rate: float
    pre_run_count: int
    post_success_rate: float
    post_run_count: int
    decline: float
    declined: bool


async def evaluate_quality_decline(
    db: Any,
    request: Any,
    *,
    pre_window_hours: float,
    min_post_window_hours: float,
    min_runs: int,
    decline_threshold: float,
) -> QualityDeclineReport | None:
    """Pure decision logic (no mutation, no git) — compares `request.
    agent_name`'s success_rate in the window BEFORE `request.completed_at`
    (the APPLY commit landing) against the window from completed_at to
    now. Returns None (not evaluable yet) when fewer than
    min_post_window_hours have elapsed since completed_at (regardless of
    run count — a handful of runs in the first few minutes is too thin a
    sample even if it happens to clear min_runs) or when either side lacks
    min_runs of real data — never guesses a decline from insufficient
    signal. `declined` is True only when post < pre - decline_threshold
    AND both windows independently clear min_runs, so a single bad run
    right after deploy can't trigger a rollback on its own.
    """
    if request.completed_at is None:
        return None

    now = datetime.now(timezone.utc)
    completed_at = request.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)

    if now - completed_at < timedelta(hours=min_post_window_hours):
        return None

    pre_start = completed_at - timedelta(hours=pre_window_hours)
    pre_rate, pre_count = await compute_success_rate_window(
        db, request.agent_name, pre_start, completed_at
    )
    post_rate, post_count = await compute_success_rate_window(
        db, request.agent_name, completed_at, now
    )

    if pre_rate is None or post_rate is None:
        return None
    if pre_count < min_runs or post_count < min_runs:
        return None

    decline = pre_rate - post_rate
    return QualityDeclineReport(
        request_id=request.id,
        agent_name=request.agent_name,
        pre_success_rate=pre_rate,
        pre_run_count=pre_count,
        post_success_rate=post_rate,
        post_run_count=post_count,
        decline=decline,
        declined=decline >= decline_threshold,
    )


async def check_and_handle_quality_decline(
    db: Any,
    request: Any,
    *,
    repo_path: str,
    pre_window_hours: float,
    min_post_window_hours: float,
    min_runs: int,
    decline_threshold: float,
) -> dict[str, Any]:
    """The real orchestration a caller (the scheduled loop, or a test)
    invokes once per eligible EnhancementRequest: evaluates decline, and
    if declined, actually performs the `git revert` and updates the row.
    Always returns a dict describing what happened (never raises) so a
    caller iterating many requests can log/continue past one failure
    without losing the others.

    Every terminal quality_check_status is written exactly once per
    request (this function is meant to be called once a request becomes
    eligible, gated by the caller on quality_check_status being NULL) —
    idempotent in the sense that a request already carrying a terminal
    status should never be passed in again, not in the sense that calling
    it twice on the same row is safe (it would revert twice).
    """
    report = await evaluate_quality_decline(
        db,
        request,
        pre_window_hours=pre_window_hours,
        min_post_window_hours=min_post_window_hours,
        min_runs=min_runs,
        decline_threshold=decline_threshold,
    )
    if report is None:
        return {"request_id": request.id, "action": "not_yet_evaluable"}

    if not report.declined:
        request.quality_check_status = "stable"
        await db.commit()
        return {"request_id": request.id, "action": "stable", "report": report}

    if not request.commit_sha:
        # A real decline with no commit to revert (commit_sha was never
        # captured, e.g. this row predates capture_commit_sha_if_verified
        # being wired in) — flag for human attention rather than silently
        # doing nothing.
        request.quality_check_status = "rollback_failed"
        await db.commit()
        logger.warning(
            "Enhancement #%s declined (%.1f%% -> %.1f%%) but has no "
            "commit_sha to revert",
            request.id,
            report.pre_success_rate * 100,
            report.post_success_rate * 100,
        )
        return {
            "request_id": request.id,
            "action": "rollback_failed_no_sha",
            "report": report,
        }

    from app.services.git_service import git_revert

    revert_result = await git_revert(repo_path, request.commit_sha)
    if revert_result["ok"]:
        request.quality_check_status = "rolled_back"
        request.rollback_commit_sha = revert_result["revertCommitSha"]
        request.rollback_at = datetime.now(timezone.utc)
        await db.commit()
        logger.warning(
            "Automatic rollback: enhancement #%s (%s) declined %.1f%% -> "
            "%.1f%% success rate — reverted commit %s as %s",
            request.id,
            request.agent_name,
            report.pre_success_rate * 100,
            report.post_success_rate * 100,
            request.commit_sha[:12],
            revert_result["revertCommitSha"][:12],
        )
        try:
            from app.fleet.fleet_events import health_updated, publish

            publish(
                health_updated(
                    request.agent_name,
                    health="degraded",
                    state=(
                        f"auto-reverted enhancement #{request.id} "
                        f"(success rate declined {report.decline * 100:.1f} pts)"
                    ),
                )
            )
        except Exception:
            logger.warning(
                "check_and_handle_quality_decline: best-effort step failed",
                exc_info=True,
            )
        return {"request_id": request.id, "action": "rolled_back", "report": report}

    request.quality_check_status = "rollback_failed"
    await db.commit()
    logger.error(
        "Enhancement #%s declined but git revert of %s FAILED: %s",
        request.id,
        request.commit_sha[:12],
        revert_result["stderr"][:500],
    )
    return {"request_id": request.id, "action": "rollback_failed", "report": report}
