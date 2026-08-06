"""Stage 4 Cluster Q (2026-08-05, STAGE4_BACKLOG.md) — Tests-only slice, the
first of the 3 honestly-shippable categories the architecture review found
(Tests / Architecture / Security), user-approved as the starting scope.

test_coverage_agent's role prompt already requires running real coverage
tooling (pytest --cov / jest --coverage) via bash and explicitly forbids
estimating a percentage — but until this fix, its submit schema
(`summary`, `findings`, `recommendations`) had no field to put the real
measured number in, so it was computed every run and discarded into
free-text prose. This fix adds `coverage_pct` to the submit schema (optional/
nullable — a genuinely blocked run, e.g. coverage tool unavailable, must
never be pressured into fabricating a number to satisfy the schema).

A second, independently real gap was found and fixed in the same change:
even with the schema field added, `app/api/specialized_agents.py`'s two real
persistence call sites (`_run_specialized_agent_bg`, `run_specialized_agent_sync`)
build their own hand-rolled `artifact_payload` dict that never included
`AgentResult.raw` — so `coverage_pct` would have been captured by the schema
and then silently discarded a second time at the artifact-write boundary,
the same "measured then discarded" bug one layer deeper. Fixed narrowly
(only for `test_coverage_agent`, not all 78 agents — out of this fix's scope
per the user-approved Tests-only slice) rather than exposing `raw` fleet-wide.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request

from app.agents.agent_result import AgentResult
from app.agents.test_coverage_agent import _SUBMIT, run_test_coverage_agent
from app.db.models import DevTask, Repo, TestScore
from app.db.repository import create_task
from app.db.session import new_isolated_async_engine
from app.fleet.test_score import get_latest_test_score


def _fake_request() -> Request:
    """Minimal real Starlette Request (not a MagicMock) — run_specialized_agent_sync
    carries a real @limiter.limit(...) decorator (app/rate_limit.py) that requires
    an actual Request instance, not just a keyword argument named `request`."""
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/specialized-agents/x/run-sync",
            "headers": [],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_submit_schema_declares_optional_nullable_coverage_pct() -> None:
    props = _SUBMIT["input_schema"]["properties"]
    assert "coverage_pct" in props
    assert set(props["coverage_pct"]["type"]) == {"number", "null"}
    # summary stays the only required field — a blocked run (coverage tool
    # unavailable) must never be forced to fabricate a number to pass schema
    # validation.
    assert _SUBMIT["input_schema"]["required"] == ["summary"]


def _fake_final_state(raw_result: dict[str, object]) -> dict[str, object]:
    return {
        "result": raw_result,
        "verification": {"read": True, "coverage_measured": True},
        "tokens_in": 100,
        "tokens_out": 50,
        "submitted": True,
    }


def test_run_test_coverage_agent_propagates_real_coverage_pct_into_raw() -> None:
    """End-to-end proof the number the model reports actually survives into
    AgentResult.raw — not just declared in the schema and then dropped
    somewhere between the graph and the return value."""
    fake_state = _fake_final_state(
        {"summary": "Reviewed auth module.", "findings": [], "coverage_pct": 87.5}
    )
    with patch(
        "app.agents.test_coverage_agent.run_agent_graph", return_value=fake_state
    ):
        result = run_test_coverage_agent(task_id=1, description="check coverage")

    assert result.raw.get("coverage_pct") == 87.5


def test_run_test_coverage_agent_blocked_run_has_no_fabricated_coverage_pct() -> None:
    """A blocked run (coverage tool never ran) must not carry a coverage_pct
    value at all — never a fabricated placeholder."""
    fake_state = _fake_final_state({"summary": "Coverage tool unavailable."})
    fake_state["verification"] = {"read": True, "coverage_measured": False}
    fake_state["submitted"] = False
    with patch(
        "app.agents.test_coverage_agent.run_agent_graph", return_value=fake_state
    ):
        result = run_test_coverage_agent(task_id=2, description="check coverage")

    assert result.raw.get("coverage_pct") is None
    assert result.status == "blocked"
    assert result.verified is False


# ---------------------------------------------------------------------------
# Dedicated test_scores persistence — added 2026-08-05 while building the
# Cluster Q cross-category aggregation layer (app/fleet/quality_score.py).
# The two tests above prove coverage_pct survives into AgentResult.raw; the
# two below prove it also flows into the real, repo-scoped test_scores
# table (app/fleet/test_score.py) that the aggregator reads from — a real
# end-to-end persistence proof against real Postgres, not just the
# in-memory AgentResult.
# ---------------------------------------------------------------------------


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clusterq-testscore-{suffix}",
                    name=f"clusterq-testscore-{suffix}",
                    local_path=f"/tmp/clusterq-testscore-{suffix}",
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
                    delete(TestScore).where(TestScore.repo_id.in_(repo_ids))
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


def test_run_test_coverage_agent_persists_real_test_score_end_to_end() -> None:
    """The score flows from the real producer (run_test_coverage_agent, with
    run_agent_graph mocked only at the LLM seam) through persistence (a real
    Postgres row) to the read-back the aggregator itself calls."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"test score e2e {suffix}", repo_id)

    fake_state = _fake_final_state(
        {"summary": "Reviewed.", "findings": [], "coverage_pct": 73.5}
    )

    try:
        with (
            patch(
                "app.agents.test_coverage_agent.run_agent_graph",
                return_value=fake_state,
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
        ):
            result = run_test_coverage_agent(
                task_id=task_id, description="check coverage"
            )

        assert result.verified is True

        latest = get_latest_test_score(repo_id)
        assert latest is not None, (
            "run_test_coverage_agent() must persist a real test_scores row "
            "for a verified run with a real coverage_pct — the end-to-end "
            "path is broken"
        )
        assert latest.coverage_pct == 73.5
        assert latest.test_score == pytest.approx(0.735)
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_run_test_coverage_agent_blocked_run_persists_no_test_score() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"test score blocked {suffix}", repo_id)

    fake_state = _fake_final_state({"summary": "Coverage tool unavailable."})
    fake_state["verification"] = {"read": True, "coverage_measured": False}
    fake_state["submitted"] = False

    try:
        with (
            patch(
                "app.agents.test_coverage_agent.run_agent_graph",
                return_value=fake_state,
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
        ):
            run_test_coverage_agent(task_id=task_id, description="check coverage")

        assert get_latest_test_score(repo_id) is None, (
            "a blocked run (no verified coverage_pct) must never persist a "
            "test_scores row"
        )
    finally:
        _cleanup_sync([task_id], [repo_id])


async def _run_bg_dispatch_and_capture_artifact(
    agent_name: str, fake_result: AgentResult
) -> dict[str, object]:
    from app.api.specialized_agents import _run_specialized_agent_bg

    mock_db = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_save = AsyncMock()

    with (
        patch("app.db.session.get_session_factory", return_value=mock_factory),
        patch("app.api.specialized_agents.append_log", new=AsyncMock()),
        patch("app.artifacts.store.save_artifact_async", new=mock_save),
        patch("app.api.repo.get_active_repo_path", return_value="/repo"),
        patch(
            "app.api.specialized_agents._load_agent_fn",
            return_value=lambda **kwargs: fake_result,
        ),
        patch("app.db.repository.get_task_repo_id", new=AsyncMock(return_value=None)),
        patch("app.memory.hooks.record_agent_run_outcome", new=AsyncMock()),
    ):
        await _run_specialized_agent_bg(
            agent_name=agent_name,
            task_id=1,
            description="d",
            repo_path=None,
        )

    assert mock_save.await_args is not None
    # save_artifact_async(task_id, agent_name, artifact_payload, agent_name, db=db)
    return mock_save.await_args.args[2]


@pytest.mark.asyncio
async def test_bg_dispatch_persists_coverage_pct_for_test_coverage_agent() -> None:
    fake_result = AgentResult(
        summary="ok", status="completed", raw={"coverage_pct": 62.3}
    )
    payload = await _run_bg_dispatch_and_capture_artifact(
        "test_coverage_agent", fake_result
    )
    assert payload["coverage_pct"] == 62.3


@pytest.mark.asyncio
async def test_bg_dispatch_does_not_add_coverage_pct_for_other_agents() -> None:
    """Regression guard for the scoped fix: this must stay a test_coverage_
    agent-specific addition, not a fleet-wide raw-dict exposure."""
    fake_result = AgentResult(summary="ok", status="completed", raw={"foo": "bar"})
    payload = await _run_bg_dispatch_and_capture_artifact("debugger_agent", fake_result)
    assert "coverage_pct" not in payload


async def _run_sync_dispatch_and_capture_artifact(
    agent_name: str, fake_result: AgentResult
) -> dict[str, object]:
    from app.api.specialized_agents import RunAgentRequest, run_specialized_agent_sync

    mock_db = AsyncMock()
    mock_save = AsyncMock()

    with (
        patch("app.api.repo.get_active_repo_path", return_value="/repo"),
        patch(
            "app.api.specialized_agents._load_agent_fn",
            return_value=lambda **kwargs: fake_result,
        ),
        patch("app.artifacts.store.save_artifact_async", new=mock_save),
        patch("app.api.specialized_agents.append_log", new=AsyncMock()),
        patch("app.db.repository.get_task", new=AsyncMock(return_value=None)),
        patch("app.memory.hooks.record_agent_run_outcome", new=AsyncMock()),
    ):
        body = RunAgentRequest(task_id=1, description="d", repo_path=None)
        await run_specialized_agent_sync(
            request=_fake_request(),
            agent_name=agent_name,
            body=body,
            db=mock_db,
            _actor="tester",
        )

    assert mock_save.await_args is not None
    return mock_save.await_args.args[2]


@pytest.mark.asyncio
async def test_run_sync_persists_coverage_pct_for_test_coverage_agent() -> None:
    fake_result = AgentResult(
        summary="ok", status="completed", raw={"coverage_pct": 91.0}
    )
    payload = await _run_sync_dispatch_and_capture_artifact(
        "test_coverage_agent", fake_result
    )
    assert payload["coverage_pct"] == 91.0


@pytest.mark.asyncio
async def test_run_sync_does_not_add_coverage_pct_for_other_agents() -> None:
    fake_result = AgentResult(summary="ok", status="completed", raw={})
    payload = await _run_sync_dispatch_and_capture_artifact(
        "debugger_agent", fake_result
    )
    assert "coverage_pct" not in payload
