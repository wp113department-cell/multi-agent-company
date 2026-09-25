"""#454 (2026-09-25, "Dependency checks as a mandatory pipeline gate") —
real gap found by direct reading: dependency_security_agent already ran as
a mandatory blocking gate (manager.py's enable_security_architecture_gates,
default True since T2-B5/#453/#455), but the blocking decision only ever
consulted vulnerable_package_count — a real license-policy violation had
NO path into it at all, despite check_target_repo_license_compliance
already being one of this agent's own allowed_tools (T2-B10/#331).

Same rigor as the pre-existing vulnerability check (see
test_stage4_cluster_q_security_score.py's own docstring for that
precedent): run_dependency_security_agent() independently re-scans
requirements.txt against real license-policy rules in code, gated on the
same graph-verified `verified` flag, never trusting whether the model's
own narrative findings mention a violation. The PyPI metadata fetch itself
is mocked here (not a real network call) — the license-CATEGORY
classification a real PyPI package carries can legitimately change over
time or be inconsistently tagged, so a live "this package is GPL" fixture
would be exactly the kind of flaky external dependency this codebase's own
sibling test (test_t2b10_target_repo_license_compliance.py) already
avoids for its own disallowed-category test.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import DevTask, Repo
from app.db.repository import create_task
from app.db.session import new_isolated_async_engine


def _make_repo_sync(suffix: str) -> int:
    import asyncio

    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/dep-license-{suffix}",
                    name=f"dep-license-{suffix}",
                    local_path=f"/tmp/dep-license-{suffix}",
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
    import asyncio

    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc", repo_id=repo_id)
                return int(task.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(task_ids: list[int], repo_ids: list[int]) -> None:
    import asyncio

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
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


def _fake_final_state(verified: bool) -> dict[str, object]:
    return {
        "result": {
            "summary": "audited",
            "findings": ["some narrative finding text"],
            "recommendations": [],
        },
        "verification": {"read": verified, "audited": verified},
        "tokens_in": 500,
        "tokens_out": 200,
        "submitted": True,
    }


def test_disallowed_license_is_counted_on_a_verified_run(tmp_path: Path) -> None:
    from app.agents.dependency_security_agent import run_dependency_security_agent

    (tmp_path / "requirements.txt").write_text("gpl-package==1.0\nmit-package==1.0\n")

    def _fake_fetch(package: str) -> tuple[str | None, list[str]]:
        if package == "gpl-package":
            return None, ["License :: OSI Approved :: GNU General Public License v3"]
        return None, ["License :: OSI Approved :: MIT License"]

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"license gate e2e {suffix}", repo_id)
    try:
        with (
            patch(
                "app.agents.dependency_security_agent.run_agent_graph",
                return_value=_fake_final_state(verified=True),
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
            patch(
                "app.policy.license_check._fetch_pypi_license_fields",
                side_effect=_fake_fetch,
            ),
            # The vulnerability side of this same verified-run block also
            # runs a real pip-audit subprocess — irrelevant to this test,
            # so kept fast/deterministic by short-circuiting it here.
            patch(
                "app.fleet.security_score.run_pip_audit_json",
                return_value=None,
            ),
        ):
            result = run_dependency_security_agent(
                task_id=task_id, description="audit deps", repo_path=str(tmp_path)
            )

        assert result.verified is True
        assert result.raw["license_disallowed_count"] == 1
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_all_allowed_licenses_count_zero_on_a_verified_run(tmp_path: Path) -> None:
    from app.agents.dependency_security_agent import run_dependency_security_agent

    (tmp_path / "requirements.txt").write_text("mit-package==1.0\n")

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"license gate e2e allowed {suffix}", repo_id)
    try:
        with (
            patch(
                "app.agents.dependency_security_agent.run_agent_graph",
                return_value=_fake_final_state(verified=True),
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
            patch(
                "app.policy.license_check._fetch_pypi_license_fields",
                return_value=(None, ["License :: OSI Approved :: MIT License"]),
            ),
            patch("app.fleet.security_score.run_pip_audit_json", return_value=None),
        ):
            result = run_dependency_security_agent(
                task_id=task_id, description="audit deps", repo_path=str(tmp_path)
            )

        assert result.verified is True
        assert result.raw["license_disallowed_count"] == 0
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_license_not_checked_at_all_on_an_unverified_run(tmp_path: Path) -> None:
    """Same invariant the pre-existing vulnerable_package_count check
    already has: an unverified (audited=False) run's claim isn't
    independently grounded — no license field should even be computed,
    the exact same honest degradation as the vulnerability side."""
    from app.agents.dependency_security_agent import run_dependency_security_agent

    (tmp_path / "requirements.txt").write_text("gpl-package==1.0\n")

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"license gate e2e unverified {suffix}", repo_id)
    try:
        with (
            patch(
                "app.agents.dependency_security_agent.run_agent_graph",
                return_value=_fake_final_state(verified=False),
            ),
            patch(
                "app.policy.license_check._fetch_pypi_license_fields",
                return_value=(
                    None,
                    ["License :: OSI Approved :: GNU General Public License v3"],
                ),
            ) as mock_fetch,
        ):
            result = run_dependency_security_agent(
                task_id=task_id, description="audit deps", repo_path=str(tmp_path)
            )

        assert result.verified is False
        assert "license_disallowed_count" not in result.raw
        mock_fetch.assert_not_called()
    finally:
        _cleanup_sync([task_id], [repo_id])
