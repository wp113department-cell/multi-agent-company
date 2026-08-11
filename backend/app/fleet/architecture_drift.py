"""Architecture Drift Detection — AUDIT_Q_BATCH16 §91 gap-closure (2026-08-11).

§91 "NO": architecture_reviewer runs its structural checks fresh every scan
with no stored baseline to compare against — each scan is stateless
relative to earlier scans, so "did technical debt increase since last time"
could not be answered, only "what does technical debt look like right now."

The regression-detection pattern already exists and works for agent quality
(app/fleet/benchmark_manager.py — real Postgres-backed baseline storage,
compare_to_baseline()'s current-vs-stored-baseline diff math). This module
applies the exact same pattern to a different, structural objectives
source: real import-graph/dead-code/circular-dependency counts (deterministic
AST analysis, app/repo_tools/ast_engine.py — never the LLM's own narrative
scan output, which has no stable structured shape to diff). Reuses
benchmark_manager's own storage functions (_write_baseline/_read_baseline —
already generic over agent_name + a plain objectives dict, the same
agent_benchmarks table, no new migration needed) and its factored-out
build_regression_report() diff math — not a parallel, duplicated baseline
store.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.fleet.benchmark_manager import (
    BenchmarkResult,
    RegressionReport,
    _read_baseline,
    _write_baseline,
    build_regression_report,
)

logger = logging.getLogger(__name__)

# A separate "agent_name" identity in the shared agent_benchmarks table —
# there is no real Agent named this; it's the storage key for the
# structural-drift baseline, mirroring how benchmark_manager itself keys
# rows by whatever name is passed to it.
_DRIFT_KEY = "architecture_drift"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ArchitectureSnapshot:
    circular_import_count: int
    dead_code_count: int
    total_import_edges: int
    timestamp: str = field(default_factory=_now_iso)


def compute_architecture_snapshot(repo_path: str) -> ArchitectureSnapshot | None:
    """Real, deterministic structural counts — never an LLM's own claim.
    Returns None when there's nothing to scan (matches ast_engine's own
    "no .py files found" / "directory not found" cases)."""
    from app.repo_tools.ast_engine import (
        _find_circular_import_cycles,
        _find_dead_code,
    )

    dead = _find_dead_code(repo_path)
    cycles_and_edges = _find_circular_import_cycles(repo_path)
    if dead is None or cycles_and_edges is None:
        return None
    cycles, total_edges = cycles_and_edges
    return ArchitectureSnapshot(
        circular_import_count=len(cycles),
        dead_code_count=len(dead),
        total_import_edges=total_edges,
    )


def _snapshot_to_objectives(snapshot: ArchitectureSnapshot) -> dict[str, float]:
    """A real "health score" where HIGHER is better (1.0 = zero issues,
    monotonically decreasing as issues accumulate) — build_regression_report()
    (shared with benchmark_manager's own agent-quality use) treats a drop in
    "benchmark_score" as a regression, so architecture *problems increasing*
    must map to this score *decreasing*, the same direction agent-quality
    regressions already use."""
    issue_count = snapshot.circular_import_count + snapshot.dead_code_count
    return {
        "circular_import_count": float(snapshot.circular_import_count),
        "dead_code_count": float(snapshot.dead_code_count),
        "total_import_edges": float(snapshot.total_import_edges),
        "benchmark_score": 1.0 / (1.0 + issue_count),
    }


def check_architecture_drift(
    repo_path: str, regression_threshold: float = 0.1
) -> RegressionReport | None:
    """Compute the current snapshot, diff it against the prior stored
    baseline (if any), then store the current snapshot as the new baseline
    — a rolling comparison against "last time", exactly the "storing each
    scan's ... counts and diffing against the prior stored scan" behavior
    §91's own Production Enhancement Plan asked for. Returns None when
    there's nothing to scan (never a fabricated all-zero report).

    regression_threshold defaults to 0.1 (10% relative drop in the composite
    health score) rather than reusing settings.benchmark_regression_threshold
    directly — that setting is documented/tuned for agent-quality objectives
    (latency/tool-accuracy/etc.), a different scale and volatility profile
    than a slow-moving structural-debt count; call sites needing a different
    sensitivity can override it."""
    snapshot = compute_architecture_snapshot(repo_path)
    if snapshot is None:
        return None

    objectives = _snapshot_to_objectives(snapshot)
    current = BenchmarkResult(agent_name=_DRIFT_KEY, objectives=objectives)

    baseline = asyncio.run(_read_baseline(_DRIFT_KEY))
    report = build_regression_report(
        _DRIFT_KEY, current, baseline, regression_threshold
    )

    try:
        asyncio.run(_write_baseline(_DRIFT_KEY, objectives))
    except Exception:
        logger.warning(
            "Could not persist architecture_drift baseline for %s",
            repo_path,
            exc_info=True,
        )

    if report.is_regression:
        logger.warning(
            "Architecture drift regression detected for %s: score %.4f -> %.4f "
            "(circular_imports=%d, dead_code=%d)",
            repo_path,
            report.baseline_score or 0.0,
            report.current_score,
            snapshot.circular_import_count,
            snapshot.dead_code_count,
        )

    return report
