"""AUDIT_Q_BATCH11 §21 "Permission system" (cross-referencing the Batch 6
finding it cites) — 12 real, confirmed GET routes across artifacts.py (2),
metrics.py (2), console.py (4), settings.py (2), and approvals.py (2) served
internal state (artifact content, cost/token metrics, repo status/log/diff/
branches, masked-key sources, secret *names*, pending approvals) with no
auth dependency at all, while every mutating route in the very same files
was correctly gated. This proves all 12 are now covered.

Deliberately scoped to exactly these 12 routes, not a whole-app GET sweep:
while fixing this, a *separate*, pre-existing gap was found — dozens of GET
routes in other, not-Batch-11 files (tasks.py, repo.py, epics.py, agents
registry, memory.py, goals.py, chat.py, specialized_agents.py,
fleet_dashboard.py) also have no auth dependency. That is real, but it is
not the Batch 6 finding Batch 11 cites, is far larger in blast radius, and
deserves its own dedicated audit/fix pass rather than being silently swept
in here — see the batch summary for this note.
"""

from __future__ import annotations

from tests.test_audit05_security_fixes import (
    _collect_dependency_names,
    _iter_leaf_routes,
)

_AUTH_DEPENDENCY_NAMES = {
    "require_approver",
    "require_authenticated",
    "get_current_user",
}

_PREVIOUSLY_OPEN_ROUTES = {
    "/api/tasks/{task_id}/artifacts",
    "/api/artifacts/{artifact_id}",
    "/api/metrics",
    "/api/metrics/epics",
    "/api/console/repos/{rpath:path}/status",
    "/api/console/repos/{rpath:path}/log",
    "/api/console/repos/{rpath:path}/diff",
    "/api/console/repos/{rpath:path}/branches",
    "/api/settings",
    "/api/settings/custom-secrets",
    "/api/approvals/pending",
    "/api/approvals/{thread_id}",
}


def test_the_12_previously_unauthenticated_batch6_routes_are_now_covered() -> None:
    """Names the exact routes the audit found open, so a future regression
    that removes just one Depends(require_authenticated) fails with a
    specific, actionable path instead of a generic sweep."""
    from app.main import app

    routes_by_path = {
        getattr(r, "path", None): r
        for r in _iter_leaf_routes(app)
        if getattr(r, "path", None) in _PREVIOUSLY_OPEN_ROUTES
    }

    missing_routes = _PREVIOUSLY_OPEN_ROUTES - routes_by_path.keys()
    assert (
        not missing_routes
    ), f"Expected route(s) not found in app — path changed? {missing_routes}"

    still_open: list[str] = []
    for path, route in routes_by_path.items():
        names = _collect_dependency_names(route.dependant)
        if not (names & _AUTH_DEPENDENCY_NAMES):
            still_open.append(path)

    assert still_open == [], f"Still unauthenticated: {still_open}"
