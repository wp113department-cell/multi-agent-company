"""Security Score — Stage 4 Cluster Q, Security slice (2026-08-05,
STAGE4_BACKLOG.md).

Computes and persists a real vulnerability-count security score from an
independently, deterministically re-run `pip-audit --format=json` against
the target repo's requirements.txt — never from
dependency_security_agent's own narrative output.

Verified before writing this module, not assumed:
  - dependency_security_agent's submit_dependency_security_agent schema
    (app/agents/tools.py) has only `findings: array[string]` — free-text
    narrative, no structured severity field at all. Unlike
    architecture_reviewer's risks[].severity (a real JSON-schema enum),
    there is nothing structured to read from the agent's own submission —
    confirmed directly, not assumed from the Cluster Q architecture
    review's original name-pattern grep.
  - pip-audit's real JSON output schema
    (pip_audit._service.interface.VulnerabilityResult, confirmed by
    reading the installed package's dataclass fields directly) is
    `id, description, fix_versions, aliases, published` — no severity
    field either. So this score is a real vulnerability COUNT, not
    severity-weighted like architecture_score — an honest difference in
    shape, not an oversight or a shortcut.
  - `npm audit` is allowed by DEPENDENCY_AUDIT_BASH_TOOL's allowlist but is
    non-functional in this project's own frontend today (pnpm, not npm —
    no package-lock.json; `npm audit --json` returns `{"error": {"code":
    "ENOLOCK", ...}}`, confirmed by running it directly) and its real
    vulnerability JSON schema was not verified in this pass. Node/npm
    dependency scoring is therefore a documented, separate gap — not
    fabricated here. See STAGE4_BACKLOG.md's Cluster Q Security slice.

Design: rather than parsing whatever text the LLM's own bash tool call
happened to produce (which may not even use --format=json, and is
truncated at 6000 chars by app.agents.tools.make_dependency_audit_bash_handler
— both of which make it an unreliable structured-data source), this module
independently re-runs pip-audit itself, deterministically, with an explicit
-r <repo>/requirements.txt and --format=json, after the agent's own run has
already verified (via real tool-execution state, not the model's claim)
that dependency-audit tooling is invokable in this environment. This keeps
app/agents/tools.py's shared bash handler completely untouched — no
behavior change for the LLM-facing path, narrowly scoped to this one new
capability.

Mirrors app/fleet/architecture_score.py and app/fleet/benchmark_manager.py's
shape: pure computation separate from tool invocation and persistence,
config-driven threshold, sync-facing entry points using
new_isolated_async_engine() per call (no AsyncSession param — no async
caller needs one yet). Only ever persisted for a verified run
(audited=True, the same graph-enforced flag AgentResult.verified already
uses) — an unverified run's tool-use claim isn't grounded, so no row is
written for it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SecurityScoreResult:
    vulnerable_package_count: int
    total_vuln_count: int
    security_score: float
    timestamp: str = field(default_factory=_now_iso)


def compute_security_score(
    pip_audit_result: dict[str, Any], settings: Any | None = None
) -> SecurityScoreResult:
    """Pure function: pip-audit's real --format=json output ->
    a bounded [0.0, 1.0] score. Reads only `dependencies[].vulns` (a real
    structured list — its length, not its contents) — never `description`
    or any other narrative field. Raises ValueError if the input doesn't
    have pip-audit's real shape (a `dependencies` list), so a parse
    failure is never silently treated as "0 vulnerabilities found"."""
    if not isinstance(pip_audit_result, dict) or "dependencies" not in pip_audit_result:
        raise ValueError(
            "pip_audit_result does not have pip-audit's real JSON shape "
            "(missing top-level 'dependencies' key) — refusing to treat a "
            "parse failure as a clean audit"
        )

    from app.config import get_settings

    s = settings or get_settings()

    vulnerable_package_count = 0
    total_vuln_count = 0
    for dep in pip_audit_result["dependencies"]:
        vulns = dep.get("vulns", [])
        if vulns:
            vulnerable_package_count += 1
            total_vuln_count += len(vulns)

    vuln_cap = max(s.security_score_vuln_cap, 1e-9)
    penalty = min(1.0, total_vuln_count / vuln_cap)
    security_score = 1.0 - penalty

    return SecurityScoreResult(
        vulnerable_package_count=vulnerable_package_count,
        total_vuln_count=total_vuln_count,
        security_score=round(security_score, 6),
    )


def run_pip_audit_json(repo_path: str, timeout: int = 120) -> dict[str, Any] | None:
    """Independently, deterministically re-run pip-audit against the real
    target repo's requirements.txt (never the caller's own runtime
    environment — pip-audit with no -r argument audits the active Python
    environment, not a target repo, which would silently score the wrong
    thing). Returns None (never raises) when there's no requirements.txt to
    audit, the tool errors, or its output isn't valid JSON — every case
    where there is no real, trustworthy structured result to build a score
    from."""
    req_path = os.path.join(repo_path, "requirements.txt")
    if not os.path.isfile(req_path):
        return None

    try:
        result = subprocess.run(
            ["pip-audit", "--format=json", "-r", req_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return dict(json.loads(result.stdout))
    except (
        subprocess.TimeoutExpired,
        FileNotFoundError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        logger.warning("pip-audit --format=json failed for %s: %s", repo_path, exc)
        return None


async def _persist(
    task_id: str, repo_id: int | None, result: SecurityScoreResult
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import SecurityScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                SecurityScore(
                    task_id=task_id,
                    repo_id=repo_id,
                    vulnerable_package_count=result.vulnerable_package_count,
                    total_vuln_count=result.total_vuln_count,
                    security_score=result.security_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_security_score(
    task_id: str, repo_id: int | None, result: SecurityScoreResult
) -> None:
    """Sync entry point for run_dependency_security_agent() (itself sync)
    to persist a score — mirrors store_architecture_score()'s own
    asyncio.run()-over-an-isolated-engine shape exactly. Non-fatal: logs
    and returns on any failure rather than raising, so a persistence
    failure can never break the real security review it's derived from."""
    try:
        asyncio.run(_persist(task_id, repo_id, result))
    except Exception as exc:
        logger.warning("Failed to persist security_score for task %s: %s", task_id, exc)


async def _read_latest(repo_id: int) -> SecurityScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import SecurityScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(SecurityScore)
                    .where(SecurityScore.repo_id == repo_id)
                    .order_by(SecurityScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return SecurityScoreResult(
                vulnerable_package_count=row.vulnerable_package_count,
                total_vuln_count=row.total_vuln_count,
                security_score=row.security_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_security_score(repo_id: int) -> SecurityScoreResult | None:
    """The intra-category 'aggregation' this slice delivers: the most
    recently persisted score for a repo. Analogous to
    architecture_score.py's get_latest_architecture_score() and
    benchmark_manager.py's _read_baseline() read path — NOT the
    cross-category Cluster Q composite, which stays out of scope until
    the Tests/Architecture/Security slices are all real (see
    STAGE4_BACKLOG.md's Cluster Q architecture review)."""
    return asyncio.run(_read_latest(repo_id))


async def _read_trend(repo_id: int, limit: int) -> list[SecurityScoreResult]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import SecurityScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                (
                    await session.execute(
                        select(SecurityScore)
                        .where(SecurityScore.repo_id == repo_id)
                        .order_by(SecurityScore.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                SecurityScoreResult(
                    vulnerable_package_count=row.vulnerable_package_count,
                    total_vuln_count=row.total_vuln_count,
                    security_score=row.security_score,
                    timestamp=row.created_at.isoformat(),
                )
                for row in rows
            ]
    finally:
        await engine.dispose()


def get_security_score_trend(
    repo_id: int, limit: int = 20
) -> list[SecurityScoreResult]:
    """Newest-first score history for a repo — the real "track improvements
    over time" capability Q117 asks for, scoped to Security only."""
    return asyncio.run(_read_trend(repo_id, limit))
