"""Release Retrospectives — AUDIT_Q_BATCH15 §115 gap-closure (2026-08-11).

"Zero code ties a 'what went well/what failed' report to any release or
deployment event" was the finding. This platform has no CI/CD deploy
pipeline of its own (confirmed by grep before writing this, same finding
_doc_agent_auto_trigger_loop's own docstring already documents for
changelog/release-notes generation), but it does have a real, already-
established "release" proxy: local `main` HEAD movement — the exact event
main.py's doc-agent auto-trigger loop already uses to autonomously fire
changelog_agent/release_notes_agent. This module hooks the same real event
to generate a retrospective, built entirely from real, already-persisted
data (DevTask outcomes, EnhancementRequest decisions) for the commit range
since the last retrospective — never LLM-narrated, so there is no
hallucination surface for "what went well/what failed" claims: every number
here is a real COUNT from a real table, and every sample is real stored
text truncated, never paraphrased or invented.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_DAYS = 7
_REPORTS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "reports"
    / "retrospectives"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ReleaseRetrospective:
    from_sha: str | None
    to_sha: str
    period_start: str
    period_end: str = field(default_factory=_now_iso)
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_blocked: int = 0
    tasks_cancelled: int = 0
    sample_failures: list[str] = field(default_factory=list)
    enhancement_requests_approved: int = 0
    enhancement_requests_rejected: int = 0
    enhancement_requests_filed: int = 0


def _resolve_period_start(
    repo_path: str, from_sha: str | None, to_sha: str
) -> datetime:
    """The real period this retrospective covers: the commit date of the
    first commit after from_sha, up to to_sha — derived from git's own real
    history, never guessed. Falls back to a fixed lookback window
    (_DEFAULT_LOOKBACK_DAYS) only when there's no prior retrospective to
    anchor to (first-ever run) or the range is empty — an explicit,
    documented default, not a silent one."""
    if from_sha:
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"{from_sha}..{to_sha}",
                    "-1",
                    "--format=%aI",
                    "--reverse",
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            date_str = result.stdout.strip()
            if result.returncode == 0 and date_str:
                return datetime.fromisoformat(date_str)
        except Exception:
            logger.debug(
                "Could not resolve retrospective period start from git", exc_info=True
            )
    return datetime.now(timezone.utc) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)


async def generate_release_retrospective(
    db: Any,
    repo_path: str,
    repo_id: int | None,
    from_sha: str | None,
    to_sha: str,
) -> ReleaseRetrospective:
    """Real aggregation over DevTask/EnhancementRequest rows for the commit
    range's real time window. Never invents a narrative — the report is
    exactly these real counts and real (truncated, not paraphrased) sample
    strings."""
    from sqlalchemy import select

    from app.db.models import DevTask, EnhancementRequest

    period_start = _resolve_period_start(repo_path, from_sha, to_sha)

    task_q = select(DevTask).where(DevTask.updated_at >= period_start)
    if repo_id is not None:
        task_q = task_q.where(DevTask.repo_id == repo_id)
    tasks = list((await db.execute(task_q)).scalars().all())

    completed = [t for t in tasks if t.status == "completed"]
    failed = [t for t in tasks if t.status == "failed"]
    blocked = [t for t in tasks if t.status == "blocked"]
    cancelled = [t for t in tasks if t.status == "cancelled"]

    sample_failures = [f"#{t.id} {t.title}"[:200] for t in (failed + blocked)[:5]]

    er_q = select(EnhancementRequest).where(
        EnhancementRequest.created_at >= period_start
    )
    ers = list((await db.execute(er_q)).scalars().all())
    approved = sum(1 for e in ers if e.status in ("approved", "applied", "completed"))
    rejected = sum(1 for e in ers if e.status == "rejected")

    return ReleaseRetrospective(
        from_sha=from_sha,
        to_sha=to_sha,
        period_start=period_start.isoformat(),
        tasks_completed=len(completed),
        tasks_failed=len(failed),
        tasks_blocked=len(blocked),
        tasks_cancelled=len(cancelled),
        sample_failures=sample_failures,
        enhancement_requests_approved=approved,
        enhancement_requests_rejected=rejected,
        enhancement_requests_filed=len(ers),
    )


def format_retrospective_markdown(r: ReleaseRetrospective) -> str:
    total = r.tasks_completed + r.tasks_failed + r.tasks_blocked + r.tasks_cancelled
    success_rate = f"{r.tasks_completed / total:.0%}" if total else "n/a"
    lines = [
        f"# Release Retrospective — {r.to_sha[:12]}",
        "",
        f"Period: {r.period_start} .. {r.period_end}",
        f"Commit range: `{r.from_sha[:12] if r.from_sha else '(none)'}..{r.to_sha[:12]}`",
        "",
        "## What went well",
        f"- {r.tasks_completed} task(s) completed successfully ({success_rate} of {total} closed this period).",
        f"- {r.enhancement_requests_approved} fleet self-improvement request(s) approved and applied.",
        "",
        "## What failed",
        f"- {r.tasks_failed} task(s) failed; {r.tasks_blocked} task(s) still blocked; {r.tasks_cancelled} cancelled.",
        f"- {r.enhancement_requests_rejected} of {r.enhancement_requests_filed} filed enhancement request(s) were rejected.",
    ]
    if r.sample_failures:
        lines.append("")
        lines.append("### Sample failed/blocked tasks")
        lines.extend(f"- {s}" for s in r.sample_failures)
    return "\n".join(lines) + "\n"


def write_retrospective_report(r: ReleaseRetrospective) -> str:
    """Write the markdown report to disk and return its path. Best-effort:
    a filesystem failure here must not be treated as "the retrospective
    failed to generate" — the caller already has the real ReleaseRetrospective
    data regardless of whether this write succeeds."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORTS_DIR / f"RETROSPECTIVE_{r.to_sha[:12]}.md"
    path.write_text(format_retrospective_markdown(r), encoding="utf-8")
    return str(path)
