"""Gap-closure Stage 1.7 (answers.md) — detects whether a set of changed
files touches "structural" code: files whose behavior changes have
fleet-wide or architectural blast radius, not routine feature work. Used
to decide whether a PR's diff should trigger tech_debt_agent in CI
(scripts/ci_tech_debt_scan.py) — kept as a pure, deterministic, real
function (no LLM call, no I/O) so it's fully unit-testable and the actual
"should this fire" decision isn't buried inside a shell glob in the CI
YAML where it can't be tested at all.
"""

from __future__ import annotations

# Chosen because each one is a real, confirmed high-blast-radius file in
# this codebase (not a guess): the shared DB schema, the two graph builders
# ~74-76 + chat_agent route through, central settings, app bootstrap,
# schema migrations, the RBAC/policy enforcement layers, and model routing.
STRUCTURAL_FILE_PATTERNS: tuple[str, ...] = (
    "backend/app/db/models.py",
    "backend/app/agents/base_graph.py",
    "backend/app/agents/chat_agent.py",
    "backend/app/config.py",
    "backend/app/main.py",
    "backend/migrations/versions/",
    "backend/app/middleware/rbac.py",
    "backend/app/policy/engine.py",
    "backend/app/fleet/model_router.py",
)


def _matches(changed_file: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return changed_file.startswith(pattern)
    return changed_file == pattern


def is_structural_file_change(changed_files: list[str]) -> bool:
    """True if any changed file matches (or, for the migrations directory
    pattern, lives under) a structural pattern."""
    return any(
        _matches(changed_file, pattern)
        for changed_file in changed_files
        for pattern in STRUCTURAL_FILE_PATTERNS
    )
