"""Project/Repo Size Awareness pre-flight — Stage 2 Days 37-38 (answers.md
Q32).

Repository size (files/bytes/extension breakdown) is *measured*, not
estimated — a real `os.walk` pass, reusing the same directory-exclusion
convention `app/agents/tools.py`'s `summarize_repo_h` already established
(`.git`/`.venv`/`node_modules`/`__pycache__`), so the numbers here and that
agent-facing summary agree on what counts.

Time/memory/disk projections follow `app/pipeline/cost_controller.py`'s own
shape exactly: prefer a real historical average from `agent_runs` when one
exists, fall back to a documented config coefficient otherwise. Two of the
four time estimates (indexing, embedding) have no comparable historical data
source at all today — `app/repo_tools/scanner.py`/`embeddings.py` record no
duration anywhere (confirmed by grep, a real named gap, not assumed) — so
those two are coefficient-only by design, not a "should be historical but
isn't wired yet" oversight. Estimated processing time uses a real historical
average of `agent_type='coder'` runs when available (the one agent type
`app/api/agents.py`'s `create_agent_run()` actually records durations for).
Estimated test-execution time is honestly coefficient-only: no `agent_runs`
row is ever written for the QA node (`base_graph.py`'s pipeline path writes
none at all — a separate, already-tracked gap), so there is no real signal
to calibrate against yet, and this module does not pretend otherwise.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

_EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


@dataclass(frozen=True)
class RepoSizeSummary:
    repo_path: str
    total_files: int
    total_dirs: int
    total_size_bytes: int
    total_size_mb: float
    ext_counts: dict[str, int] = field(default_factory=dict)


def measure_repo_size(repo_path: str) -> RepoSizeSummary:
    """Real, measured — walks the tree once. A file that vanishes mid-walk
    (race) or can't be stat'd (permissions) is skipped, never raised —
    matches resource_check.py's "a probe never crashes its caller" design."""
    total_files = 0
    total_dirs = 0
    total_size_bytes = 0
    ext_counts: dict[str, int] = {}

    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        total_dirs += len(dirnames)
        for fname in filenames:
            total_files += 1
            ext = os.path.splitext(fname)[1] or "other"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            try:
                total_size_bytes += os.path.getsize(os.path.join(dirpath, fname))
            except OSError:
                continue

    return RepoSizeSummary(
        repo_path=repo_path,
        total_files=total_files,
        total_dirs=total_dirs,
        total_size_bytes=total_size_bytes,
        total_size_mb=total_size_bytes / (1024**2),
        ext_counts=ext_counts,
    )


@dataclass(frozen=True)
class SizeEstimate:
    repo: RepoSizeSummary
    estimated_disk_required_mb: float
    estimated_memory_required_mb: float
    estimated_indexing_seconds: float
    estimated_embedding_seconds: float
    estimated_processing_seconds: float
    processing_source: str  # "historical" | "config_fallback"
    estimated_test_execution_seconds: float
    test_execution_source: str  # always "config_fallback" today — see module docstring


async def historical_avg_duration_seconds(
    db: AsyncSession, agent_type: str
) -> float | None:
    """Mirrors cost_controller.py's own _historical_avg_tokens() shape:
    None when no completed, timed rows exist for this agent_type. Public
    (not module-private) — gap-closure Day 39 reuses this directly from
    cost_controller.py's estimate_epic_cost() rather than duplicating the
    query, per this plan's own reuse-don't-duplicate standard."""
    from app.db.models import AgentRun

    result = await db.execute(
        select(
            func.avg(func.extract("epoch", AgentRun.finished_at - AgentRun.started_at))
        ).where(
            AgentRun.agent_type == agent_type,
            AgentRun.status == "completed",
            AgentRun.finished_at.isnot(None),
        )
    )
    avg = result.scalar()
    return float(avg) if avg is not None else None


async def estimate_project_size(
    repo_path: str,
    db: AsyncSession | None = None,
    subtask_count: int = 1,
) -> SizeEstimate:
    """`db=None` skips the historical lookup entirely (pure/offline use,
    mirrors cost_controller's estimate_epic_cost_sync split) and always
    uses the config fallback for processing time."""
    settings = get_settings()
    repo = measure_repo_size(repo_path)

    estimated_disk_required_mb = repo.total_size_mb * settings.size_disk_multiplier
    estimated_memory_required_mb = repo.total_files * settings.size_memory_mb_per_file
    estimated_indexing_seconds = (
        repo.total_files * settings.size_indexing_seconds_per_file
    )
    estimated_embedding_seconds = (
        repo.total_files * settings.size_embedding_seconds_per_file
    )

    processing_source = "config_fallback"
    processing_per_subtask = settings.size_processing_seconds_fallback_per_subtask
    if db is not None:
        historical = await historical_avg_duration_seconds(db, "coder")
        if historical is not None:
            processing_per_subtask = historical
            processing_source = "historical"
    estimated_processing_seconds = processing_per_subtask * max(subtask_count, 1)

    return SizeEstimate(
        repo=repo,
        estimated_disk_required_mb=estimated_disk_required_mb,
        estimated_memory_required_mb=estimated_memory_required_mb,
        estimated_indexing_seconds=estimated_indexing_seconds,
        estimated_embedding_seconds=estimated_embedding_seconds,
        estimated_processing_seconds=estimated_processing_seconds,
        processing_source=processing_source,
        estimated_test_execution_seconds=settings.size_test_execution_seconds_fallback,
        test_execution_source="config_fallback",
    )
