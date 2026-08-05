"""Stage 4 Cluster Q (2026-08-05, STAGE4_BACKLOG.md) — Security slice.

Verified before writing any aggregation logic (per user instruction) that
dependency_security_agent's own submission is NOT sufficient structured
data: submit_dependency_security_agent's schema (app/agents/tools.py) has
only `findings: array[string]` — free-text narrative, no structured
severity field at all, a genuinely different (less-structured) shape than
architecture_reviewer's risks[].severity enum. Also verified pip-audit's
own real JSON schema (pip_audit._service.interface.VulnerabilityResult,
read directly from the installed package) has no severity field either —
id/description/fix_versions/aliases/published only. So this score is a
real vulnerability COUNT, built by independently re-running pip-audit
ourselves (never parsing the agent's narrative findings) — the honest
"canonical machine-readable output" path, not a shortcut.

Real end-to-end path proven here, matching the same discipline as the
Architecture slice:
  1. A real producer: run_pip_audit_json() independently, deterministically
     re-runs the real pip-audit CLI (not mocked) against a real, isolated
     requirements.txt.
  2. compute_security_score() turns that into a bounded [0,1] score.
  3. store_security_score() persists it to a real Postgres row — gated on
     the run's real `audited` verification flag, never an unverified claim.
  4. get_latest_security_score()/get_security_score_trend() read it back —
     the intra-category "aggregation" this slice delivers.

Every DB-touching test uses real Postgres (no mocked DB). The end-to-end
test exercises the real pip-audit CLI subprocess (not mocked) against
`requests==2.32.3`, a version with 2 permanently-real, historically fixed
CVEs (PYSEC-2026-1872, PYSEC-2026-2275) — CVEs against an already-pinned
old version never get retracted, so this is a deterministic, stable
non-zero fixture, not a flaky live-data dependency.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import DevTask, Repo, SecurityScore
from app.db.repository import create_task
from app.db.session import new_isolated_async_engine
from app.fleet.security_score import (
    compute_security_score,
    get_latest_security_score,
    get_security_score_trend,
    run_pip_audit_json,
    store_security_score,
)

# ---------------------------------------------------------------------------
# compute_security_score() — pure function, no DB, no subprocess
# ---------------------------------------------------------------------------


def test_clean_audit_scores_1_vacuously() -> None:
    result = compute_security_score({"dependencies": [{"name": "x", "vulns": []}]})
    assert result.security_score == 1.0
    assert result.total_vuln_count == 0
    assert result.vulnerable_package_count == 0


def test_vuln_counts_applied_correctly() -> None:
    settings = SimpleNamespace(security_score_vuln_cap=5.0)
    pip_audit_result = {
        "dependencies": [
            {"name": "clean-pkg", "version": "1.0", "vulns": []},
            {
                "name": "vulnerable-pkg",
                "version": "0.1",
                "vulns": [{"id": "PYSEC-1"}, {"id": "PYSEC-2"}],
            },
        ]
    }
    result = compute_security_score(pip_audit_result, settings=settings)
    assert result.vulnerable_package_count == 1
    assert result.total_vuln_count == 2
    assert result.security_score == pytest.approx(1.0 - 2 / 5.0)


def test_score_clamps_at_zero_never_negative() -> None:
    settings = SimpleNamespace(security_score_vuln_cap=1.0)
    pip_audit_result = {
        "dependencies": [
            {
                "name": "very-vulnerable",
                "vulns": [{"id": f"PYSEC-{i}"} for i in range(10)],
            }
        ]
    }
    result = compute_security_score(pip_audit_result, settings=settings)
    assert result.security_score == 0.0
    assert result.total_vuln_count == 10


def test_malformed_input_raises_never_silently_treated_as_clean() -> None:
    """A parse failure (missing pip-audit's real 'dependencies' key) must
    raise, not be silently scored as a clean audit — the caller's
    try/except then correctly skips persistence instead of writing a false
    security_score=1.0 row."""
    with pytest.raises(ValueError):
        compute_security_score({"unexpected_shape": True})


def test_compute_reads_only_vulns_list_never_narrative_description() -> None:
    """The score must be identical regardless of what a vuln's description
    text says — proving it's built purely from the structured vulns list
    length, never narrative content."""
    terse = {
        "dependencies": [
            {"name": "x", "vulns": [{"id": "PYSEC-1", "description": "short"}]}
        ]
    }
    verbose = {
        "dependencies": [
            {
                "name": "x",
                "vulns": [
                    {
                        "id": "PYSEC-1",
                        "description": "a very long narrative description "
                        "implying this should obviously be scored as far "
                        "more severe based on prose alone",
                    }
                ],
            }
        ]
    }
    assert (
        compute_security_score(terse).security_score
        == compute_security_score(verbose).security_score
    )


# ---------------------------------------------------------------------------
# run_pip_audit_json() — real subprocess, no DB
# ---------------------------------------------------------------------------


def test_run_pip_audit_json_returns_none_when_no_requirements_file(
    tmp_path: Path,
) -> None:
    result = run_pip_audit_json(str(tmp_path))
    assert result is None


def test_run_pip_audit_json_real_tool_call_against_known_vulnerable_package(
    tmp_path: Path,
) -> None:
    """Not mocked — the real pip-audit CLI, run against a real, isolated
    requirements.txt pinning requests==2.32.3 (2 permanently-real,
    historically-fixed CVEs)."""
    (tmp_path / "requirements.txt").write_text("requests==2.32.3\n")

    result = run_pip_audit_json(str(tmp_path))

    assert result is not None
    assert "dependencies" in result
    score = compute_security_score(result)
    assert score.vulnerable_package_count == 1
    assert score.total_vuln_count == 2


def test_run_pip_audit_json_real_tool_call_against_clean_package(
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text("requests==2.33.0\n")

    result = run_pip_audit_json(str(tmp_path))

    assert result is not None
    score = compute_security_score(result)
    assert score.total_vuln_count == 0
    assert score.security_score == 1.0


# ---------------------------------------------------------------------------
# Real-Postgres persistence + read-back
# ---------------------------------------------------------------------------


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clusterq-sec-{suffix}",
                    name=f"clusterq-sec-{suffix}",
                    local_path=f"/tmp/clusterq-sec-{suffix}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
                return int(repo.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _make_task_sync(title: str, repo_id: int | None) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc", repo_id=repo_id)
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(task_ids: list[int], repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(SecurityScore).where(SecurityScore.repo_id.in_(repo_ids))
                )
                if task_ids:
                    await session.execute(
                        delete(DevTask).where(DevTask.id.in_(task_ids))
                    )
                if repo_ids:
                    await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_store_and_read_back_latest_score_real_postgres() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"security audit {suffix}", repo_id)

    try:
        assert get_latest_security_score(repo_id) is None

        result = compute_security_score(
            {"dependencies": [{"name": "x", "vulns": [{"id": "PYSEC-1"}]}]}
        )
        store_security_score(str(task_id), repo_id, result)

        latest = get_latest_security_score(repo_id)
        assert latest is not None
        assert latest.security_score == result.security_score
        assert latest.total_vuln_count == 1
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_trend_returns_newest_first_real_postgres() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"security audit trend {suffix}", repo_id)

    try:
        clean = compute_security_score({"dependencies": []})  # 1.0
        vulnerable = compute_security_score(
            {
                "dependencies": [
                    {"name": "x", "vulns": [{"id": f"PYSEC-{i}"} for i in range(5)]}
                ]
            },
            settings=SimpleNamespace(security_score_vuln_cap=5.0),
        )  # 0.0
        store_security_score(str(task_id), repo_id, clean)
        store_security_score(str(task_id), repo_id, vulnerable)

        trend = get_security_score_trend(repo_id, limit=10)
        assert len(trend) == 2
        assert trend[0].security_score == 0.0
        assert trend[1].security_score == 1.0
    finally:
        _cleanup_sync([task_id], [repo_id])


# ---------------------------------------------------------------------------
# End-to-end: real producer (run_dependency_security_agent) -> real
# pip-audit subprocess -> persistence -> read-back
# ---------------------------------------------------------------------------


def _fake_final_state(verified: bool) -> dict[str, object]:
    return {
        "result": {
            "summary": "audited",
            "findings": [
                "some narrative finding text — must never be parsed for scoring"
            ],
            "recommendations": [],
        },
        "verification": {"read": verified, "audited": verified},
        "tokens_in": 500,
        "tokens_out": 200,
        "submitted": True,
    }


def test_run_dependency_security_agent_end_to_end_persists_real_score(
    tmp_path: Path,
) -> None:
    """The literal proof the user asked for: the score flows from the real
    producer (run_dependency_security_agent, with run_agent_graph mocked
    only at the LLM seam — the real pip-audit CLI subprocess call is NOT
    mocked) through persistence (a real Postgres row) to the final
    aggregation (get_latest_security_score's read-back)."""
    from app.agents.dependency_security_agent import run_dependency_security_agent

    (tmp_path / "requirements.txt").write_text("requests==2.32.3\n")

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"security e2e {suffix}", repo_id)

    try:
        with (
            patch(
                "app.agents.dependency_security_agent.run_agent_graph",
                return_value=_fake_final_state(verified=True),
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
        ):
            result = run_dependency_security_agent(
                task_id=task_id, description="audit deps", repo_path=str(tmp_path)
            )

        assert result.verified is True

        latest = get_latest_security_score(repo_id)
        assert latest is not None, (
            "run_dependency_security_agent() must persist a real "
            "security_scores row for a verified run — the end-to-end path "
            "is broken"
        )
        assert latest.vulnerable_package_count == 1
        assert latest.total_vuln_count == 2
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_run_dependency_security_agent_unverified_run_persists_no_score(
    tmp_path: Path,
) -> None:
    """An unverified run's audit claim isn't independently grounded in real
    tool output — no row must be written for it, never a score built on an
    unverified claim."""
    from app.agents.dependency_security_agent import run_dependency_security_agent

    (tmp_path / "requirements.txt").write_text("requests==2.32.3\n")

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"security unverified {suffix}", repo_id)

    try:
        with (
            patch(
                "app.agents.dependency_security_agent.run_agent_graph",
                return_value=_fake_final_state(verified=False),
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
        ):
            result = run_dependency_security_agent(
                task_id=task_id, description="audit deps", repo_path=str(tmp_path)
            )

        assert result.verified is False
        assert (
            get_latest_security_score(repo_id) is None
        ), "an unverified run must never persist a security_score row"
    finally:
        _cleanup_sync([task_id], [repo_id])
