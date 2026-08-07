"""Governance policy — framework-approval enforcement.

AUDIT_Q_BATCH11 §85 "Central governance system beyond the security-focused
policy engine" — "'Governance' appears only as descriptive prose in
comments [roles/_GLOBAL_STANDARDS.md], not as an enforcement engine... what
exists is a well-built *security* policy engine (command/path denylists)
that gets conflated with governance in casual description but serves a
narrower purpose."

This module is deliberately kept separate from app.policy.engine (the
security policy engine) rather than adding "one more rule" to it — the
audit's own point is that governance (architecture/framework boundaries)
and security (credential/command/path safety) are different concerns that
should not be conflated, even though both plug into the same
_policy_check() chokepoint (app/agents/base_graph.py) for enforcement.

Scope, honestly stated: this enforces exactly one concrete, evidence-backed
rule — framework-approval for the backend/frontend boundary this project's
own README.md documents (`backend/ → FastAPI + LangGraph backend (Python
3.11+)`, `apps/web/ → Next.js frontend (TypeScript, App Router)`). It does
NOT attempt to enforce "coding standards" or "naming conventions" —
roles/_GLOBAL_STANDARDS.md's own rules (SOLID/KISS/DRY, "no drive-by
improvements", "production quality bar") are inherently qualitative
judgment calls a human reviewer or an LLM's own judgment can assess, not
properties a regex/AST check can verify without inventing an arbitrary,
unfounded proxy for what "clean code" means at this project. Building a
fake "coding standards checker" around invented rules would itself violate
the zero-hallucination bar this same audit effort is held to — see the
batch summary for this scope boundary stated explicitly, not silently
omitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_DISALLOWED_BACKEND_JS_FRAMEWORKS = (
    "express",
    "koa",
    "fastify",
    "hapi",
    "restify",
    "@nestjs/core",
    "nestjs",
    "koa-router",
    "sails",
    "loopback",
)

# The one legitimate JS/TS surface this project's README.md documents.
_APPROVED_JS_SURFACE_PREFIX = "apps/web/"


@dataclass
class GovernanceResult:
    allowed: bool
    reason: str = ""


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def check_backend_framework_governance(
    path: str, content: str = ""
) -> GovernanceResult:
    """Deny introducing a Node.js backend-web-framework dependency inside
    `backend/` — this project's real, README-documented architecture
    reserves Node.js/TypeScript for `apps/web/` (the Next.js frontend)
    only; `backend/` is FastAPI + LangGraph + Python. Grepped first
    (2026-08-07): zero `package.json` currently exists anywhere under
    `backend/`, and the one existing `.js` file there
    (tests/load/gridiron_load_test.js, a k6 load-test script) is not a
    backend-framework file — so this only ever fires for a genuinely new,
    unprecedented file, never an existing legitimate one.

    Checked on `package.json` writes specifically (not every `.js`/`.ts`
    file — a blanket file-extension ban would false-positive on legitimate
    JS tooling like the load-test script above); `content` is the file
    body being written, parsed as JSON to inspect declared dependencies.
    """
    normalized = _normalize(path)
    if normalized.startswith(_APPROVED_JS_SURFACE_PREFIX):
        return GovernanceResult(allowed=True)

    if normalized != "package.json" and not normalized.endswith("/package.json"):
        return GovernanceResult(allowed=True)

    if not content:
        return GovernanceResult(allowed=True)
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return GovernanceResult(allowed=True)
    if not isinstance(parsed, dict):
        return GovernanceResult(allowed=True)

    all_deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = parsed.get(key)
        if isinstance(deps, dict):
            all_deps.update(deps)

    for dep_name in all_deps:
        lowered = dep_name.lower()
        if lowered in _DISALLOWED_BACKEND_JS_FRAMEWORKS or any(
            lowered.startswith(f + "/") for f in _DISALLOWED_BACKEND_JS_FRAMEWORKS
        ):
            return GovernanceResult(
                allowed=False,
                reason=(
                    f"Governance denied: {path!r} declares Node.js backend-"
                    f"framework dependency {dep_name!r}. This project's "
                    "architecture (README.md) reserves backend/ for "
                    "FastAPI + LangGraph + Python; Node.js/TypeScript is "
                    "approved only for apps/web/ (the Next.js frontend). "
                    "If a new backend service is genuinely intended, this "
                    "is an architecture decision requiring explicit human "
                    "sign-off, not something an agent should introduce "
                    "unilaterally."
                ),
            )
    return GovernanceResult(allowed=True)
