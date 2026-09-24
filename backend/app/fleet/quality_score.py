"""Cross-category Quality Score aggregation — Stage 4 Cluster Q aggregation
layer (2026-08-05, STAGE4_BACKLOG.md).

Combines the persisted, structured per-category score records from Tests
(app/fleet/test_score.py), Architecture (app/fleet/architecture_score.py),
Security (app/fleet/security_score.py), Memory (app/fleet/memory_score.py),
Agents (app/fleet/agents_score.py, AUDIT_Q_BATCH15 §117 gap-closure,
2026-08-11), Tools (app/fleet/tools_score.py) and Prompts
(app/fleet/prompts_score.py, both T2-B7, 2026-09-24, GRIDIRON_PARTIAL
#414) — 7 of 9 categories production-verified today — into a single,
extensible aggregation. Never recomputes a category's score: reads only
each category's own get_latest_*_score(repo_id) read-back function, which
itself only reads the last persisted row, computed and verified at write
time by that category's own real producer.

Categories not yet implemented (Documentation, Performance — see
STAGE4_BACKLOG.md's Cluster Q architecture review, and _NOT_YET_IMPLEMENTED's
own comment below for why these two specifically still have no real signal
to build on) report status="unavailable", reason="not_implemented" — never
a placeholder/zero/fabricated score. A category that IS implemented but has
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
#   - documentation: zero real structured signal anywhere, re-confirmed
#     directly before this pass, not assumed.
#   - tools, prompts: CLOSED, T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414).
#     "tools" reads AgentRun.tool_accuracy (migration 057, itself new this
#     batch — see app/fleet/tools_score.py). "prompts" reads
#     regression_detector.check_agent()'s real deploy-gate pass/fail per
#     relevant role (see app/fleet/prompts_score.py for why this is a
#     genuinely distinct signal from "agents" below, not a duplicate).
#     No longer listed here — see _category_registry() below.
#   - performance: no real app-runtime signal exists; the only real
#     latency data (agent_benchmarks.objectives.latency_p50) measures
#     agent orchestration time, not application performance — a different
#     design boundary than "agents" below (that data now IS wired in for
#     its own real purpose; "performance" would mean the deployed target
#     app's own runtime characteristics, which this platform has no
#     instrumentation hook into for an arbitrary target repo).
#   - agents: AUDIT_Q_BATCH15 §117 gap-closure (2026-08-11) — the design
#     decision this comment used to describe as "not yet made" is now made
#     and wired (app/fleet/agents_score.py): a repo-derived join through
#     agent_runs.task_id -> dev_tasks.repo_id resolves the real set of
#     agent_names that actually ran against a given repo, and their own
#     already-real, already-persisted baseline benchmark_score
#     (agent_benchmarks.is_baseline=True) is averaged into one per-repo
#     score. No longer listed here — see _category_registry() below.
# Listed explicitly so each shows up as "unavailable"/"not_implemented" in
# the aggregate rather than being silently absent from it. Adding a real
# producer later means removing the name from here and adding a category
# function below, registered in _category_registry() — the aggregation
# logic itself never changes.
_NOT_YET_IMPLEMENTED = (
    "documentation",
    "performance",
)


def _category_registry() -> list[CategoryDefinition]:
    """Built fresh per call, not a module-level constant — imports stay
    lazy so this aggregator doesn't force an import-time dependency on
    every category module it can report on (mirrors this project's own
    lazy-import convention throughout app/fleet and app/agents)."""
    from app.fleet.agents_score import get_latest_agents_score
    from app.fleet.architecture_score import get_latest_architecture_score
    from app.fleet.memory_score import get_latest_memory_score
    from app.fleet.prompts_score import get_latest_prompts_score
    from app.fleet.security_score import get_latest_security_score
    from app.fleet.test_score import get_latest_test_score
    from app.fleet.tools_score import get_latest_tools_score

    categories = [
        CategoryDefinition("tests", True, get_latest_test_score, "test_score"),
        CategoryDefinition(
            "architecture", True, get_latest_architecture_score, "architecture_score"
        ),
        CategoryDefinition(
            "security", True, get_latest_security_score, "security_score"
        ),
        CategoryDefinition("memory", True, get_latest_memory_score, "memory_score"),
        # AUDIT_Q_BATCH15 §117 gap-closure (2026-08-11).
        CategoryDefinition("agents", True, get_latest_agents_score, "agents_score"),
        # T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414).
        CategoryDefinition("tools", True, get_latest_tools_score, "tools_score"),
        CategoryDefinition("prompts", True, get_latest_prompts_score, "prompts_score"),
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
