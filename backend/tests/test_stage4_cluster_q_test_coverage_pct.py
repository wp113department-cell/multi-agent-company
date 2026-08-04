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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.agent_result import AgentResult
from app.agents.test_coverage_agent import _SUBMIT, run_test_coverage_agent


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
            agent_name=agent_name, body=body, db=mock_db, _actor="tester"
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
    payload = await _run_sync_dispatch_and_capture_artifact("debugger_agent", fake_result)
    assert "coverage_pct" not in payload
