"""Cross-category Quality Score aggregation — Stage 4 Cluster Q aggregation
layer (2026-08-05, STAGE4_BACKLOG.md).

Combines the persisted, structured per-category score records from Tests
(app/fleet/test_score.py), Architecture (app/fleet/architecture_score.py),
and Security (app/fleet/security_score.py) — the 3 categories that are
production-verified today — into a single, extensible aggregation. Never
recomputes a category's score: reads only each category's own
get_latest_*_score(repo_id) read-back function, which itself only reads
the last persisted row, computed and verified at write time by that
category's own real producer.

Categories not yet implemented (Documentation, Performance, Memory, Tools,
Agents, Prompts — see STAGE4_BACKLOG.md's Cluster Q architecture review)
report status="unavailable", reason="not_implemented" — never a
placeholder/zero/fabricated score. A category that IS implemented but has
no persisted score yet for a given repo (its real producer has never run
against that repo) also reports status="unavailable", but reason="no_data"
— distinct from "not_implemented" so a caller can tell "this category
doesn't exist yet" from "this category exists but hasn't scored this repo
yet."

Extensibility: adding a future category (once its own score module and
get_latest_*_score(repo_id) function exist, matching this file's own
established shape) means adding one CategoryDefinition entry to
_category_registry() and removing its name from _NOT_YET_IMPLEMENTED —
nothing else changes; the aggregation logic itself is category-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CategoryDefinition:
    name: str
    implemented: bool
    # None when not implemented. Takes repo_id, returns the category's own
    # already-computed, already-persisted *Result dataclass instance, or
    # None if no row exists yet for this repo. Never invoked to compute a
    # new score — only to read the latest one already on record.
    get_latest: Callable[[int], Any] | None
    # Attribute name on the returned *Result object holding the real
    # [0.0, 1.0] score — e.g. "architecture_score".
    score_attr: str


# Categories with no real producer yet (Stage 4 Cluster Q architecture
# review + the per-category re-verification pass, STAGE4_BACKLOG.md):
#   - documentation, prompts: zero real structured signal anywhere,
#     re-confirmed directly before this pass, not assumed.
#   - tools: ToolCallRecord (app/fleet/metrics.py) is transient in-memory
#     per-run data only — never persisted to any table, let alone one with
#     repo scoping. No structured record to aggregate.
#   - performance: no real app-runtime signal exists; the only real
#     latency data (agent_benchmarks.objectives.latency_p50) measures
#     agent orchestration time, not application performance, and shares
#     the same agent-name (not repo) scoping problem as "agents" below.
#   - agents: benchmark_manager.py/agent_benchmarks IS a real, working
#     producer (unlike the other 5) — but it's scoped by agent_name, not
#     repo_id (confirmed: agent_benchmarks has no repo_id column at all).
#     An agent like "architect" runs across many repos; its execution-
#     quality score isn't a property of any one repo. Wiring this into a
#     per-repo aggregator requires a real design decision (fleet-wide
#     score vs. a repo-derived join through agent_runs/dev_tasks) not yet
#     made — listed here as blocked-by-design-decision, not
#     blocked-by-missing-data, until that choice is made.
# Listed explicitly so each shows up as "unavailable"/"not_implemented" in
# the aggregate rather than being silently absent from it. Adding a real
# producer later means removing the name from here and adding a category
# function below, registered in _category_registry() — the aggregation
# logic itself never changes.
_NOT_YET_IMPLEMENTED = (
    "documentation",
    "performance",
    "tools",
    "agents",
    "prompts",
)


def _category_registry() -> list[CategoryDefinition]:
    """Built fresh per call, not a module-level constant — imports stay
    lazy so this aggregator doesn't force an import-time dependency on
    every category module it can report on (mirrors this project's own
    lazy-import convention throughout app/fleet and app/agents)."""
    from app.fleet.architecture_score import get_latest_architecture_score
    from app.fleet.memory_score import get_latest_memory_score
    from app.fleet.security_score import get_latest_security_score
    from app.fleet.test_score import get_latest_test_score

    categories = [
        CategoryDefinition("tests", True, get_latest_test_score, "test_score"),
        CategoryDefinition(
            "architecture", True, get_latest_architecture_score, "architecture_score"
        ),
        CategoryDefinition(
            "security", True, get_latest_security_score, "security_score"
        ),
        CategoryDefinition("memory", True, get_latest_memory_score, "memory_score"),
    ]
    categories.extend(
        CategoryDefinition(name, False, None, "") for name in _NOT_YET_IMPLEMENTED
    )
    return categories


@dataclass
class CategoryScoreView:
    name: str
    status: str  # "available" | "unavailable"
    score: float | None = None
    reason: str | None = None  # "not_implemented" | "no_data" — only when unavailable
    detail: Any | None = None  # the real per-category *Result object, when available


@dataclass
class QualityScoreResult:
    repo_id: int
    categories: list[CategoryScoreView]
    overall_score: float | None
    available_category_count: int
    total_category_count: int
    timestamp: str = field(default_factory=_now_iso)


def get_quality_score(repo_id: int) -> QualityScoreResult:
    """The cross-category aggregation. Reads ONLY each category's own
    latest persisted score record — never recomputes a category score
    itself. overall_score is the mean of available categories' scores
    only; unavailable categories are excluded from the average entirely,
    never treated as 0 (a repo with 1 real category scored and 8 not-yet-
    implemented must show that 1 category's real score, not an average
    dragged toward 0 by 8 fabricated zeros)."""
    views: list[CategoryScoreView] = []
    available_scores: list[float] = []

    for cat in _category_registry():
        if not cat.implemented or cat.get_latest is None:
            views.append(
                CategoryScoreView(
                    name=cat.name, status="unavailable", reason="not_implemented"
                )
            )
            continue

        result = cat.get_latest(repo_id)
        if result is None:
            views.append(
                CategoryScoreView(name=cat.name, status="unavailable", reason="no_data")
            )
            continue

        score = getattr(result, cat.score_attr)
        views.append(
            CategoryScoreView(
                name=cat.name, status="available", score=score, detail=result
            )
        )
        available_scores.append(score)

    overall = (
        round(sum(available_scores) / len(available_scores), 6)
        if available_scores
        else None
    )

    return QualityScoreResult(
        repo_id=repo_id,
        categories=views,
        overall_score=overall,
        available_category_count=len(available_scores),
        total_category_count=len(views),
    )
