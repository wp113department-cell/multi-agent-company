"""check_dependency_conflicts tool — T2-B5 (2026-09-22, GRIDIRON_PARTIAL
#463 "Dependency conflicts (real solver, not just pip check)").

Exposes app.fleet.dependency_resolver's real resolvelib-backed resolver as
an agent tool: given a set of proposed top-level requirement constraints
(e.g. ["django>=4.2,<5.0", "celery>=5.3"]), answers whether they can ALL be
satisfied simultaneously across their real transitive PyPI dependency
trees — genuinely new capability `pip check` (installed-environment-only)
cannot provide, since a proposed upgrade isn't installed yet.
"""

from __future__ import annotations

from typing import Any

from app.fleet.dependency_resolver import check_dependency_conflicts

CHECK_DEPENDENCY_CONFLICTS_TOOL: dict[str, Any] = {
    "name": "check_dependency_conflicts",
    "description": (
        "Real SAT-solver-style check: can this set of proposed PyPI requirement "
        "constraints (e.g. 'django>=4.2,<5.0') all be satisfied simultaneously, "
        "including their full real transitive dependency trees? Use this BEFORE "
        "recommending a version upgrade that changes more than one pinned "
        "dependency, or whenever two proposed upgrades might conflict — pip check "
        "alone only audits what is already installed, it cannot evaluate a "
        "proposed set of versions that isn't installed yet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "PyPI requirement strings, e.g. ['django>=4.2,<5.0', 'celery>=5.3']",
            }
        },
        "required": ["requirements"],
    },
}


def check_dependency_conflicts_handler(inp: dict[str, Any]) -> str:
    requirements = inp.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return "[ERROR] requirements must be a non-empty list of requirement strings"

    result = check_dependency_conflicts([str(r) for r in requirements])

    if result.error is not None:
        return f"[ERROR] check_dependency_conflicts: {result.error}"
    if not result.resolvable:
        return (
            "CONFLICT: no combination of versions satisfies every constraint "
            f"simultaneously. {result.conflict_summary or ''}".strip()
        )
    resolved = ", ".join(
        f"{name}=={ver}" for name, ver in sorted(result.resolved_versions.items())
    )
    return f"Resolvable: {resolved}" if resolved else "Resolvable (no packages needed)."
