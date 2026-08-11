"""Tests for AUDIT_Q_BATCH15 §118 gap-closure — main.py's
_run_prompt_auto_rollback_once(), the missing automatic trigger connecting
regression_detector.check_fleet() (real, pre-existing) to
prompt_registry.rollback() (real, pre-existing, previously dead code).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _run_prompt_auto_rollback_once


@dataclass
class _FakeReport:
    current_score: float
    baseline_score: float | None
    delta: float


@dataclass
class _FakeGate:
    agent_name: str
    blocked: bool
    report: _FakeReport


def _factory_returning(db: AsyncMock):
    @asynccontextmanager
    async def _ctx():
        yield db

    return MagicMock(return_value=_ctx())


@pytest.mark.asyncio
async def test_rolls_back_a_regressed_agent_with_a_real_deployed_prompt() -> None:
    gate = _FakeGate(
        agent_name="td_rollback_agent",
        blocked=True,
        report=_FakeReport(current_score=0.4, baseline_score=0.9, delta=-0.5),
    )
    mock_detector = MagicMock()
    mock_detector.check_fleet.return_value = [gate]

    mock_registry = MagicMock()
    mock_registry.get_deployed.return_value = SimpleNamespace(id=2)
    mock_registry.rollback.return_value = SimpleNamespace(version_number=1)

    mock_db = AsyncMock()

    with (
        patch(
            "app.fleet.regression_detector.get_regression_detector",
            return_value=mock_detector,
        ),
        patch(
            "app.fleet.prompt_registry.get_prompt_registry", return_value=mock_registry
        ),
        patch(
            "app.db.session.get_session_factory",
            return_value=_factory_returning(mock_db),
        ),
        patch("app.db.repository.get_setting", new=AsyncMock(return_value=None)),
        patch("app.db.repository.set_setting", new=AsyncMock()) as mock_set_setting,
    ):
        await _run_prompt_auto_rollback_once()

    mock_registry.rollback.assert_called_once_with("td_rollback_agent")
    mock_set_setting.assert_called_once()
    assert (
        mock_set_setting.call_args.args[1]
        == "prompt_auto_rollback_last_at:td_rollback_agent"
    )


@pytest.mark.asyncio
async def test_skips_agent_with_no_deployed_prompt_version() -> None:
    """A regressed benchmark for an agent that was never versioned through
    prompt_registry (no roles/*.md ever went through propose/deploy) has
    nothing to roll back — must not raise, must not call rollback()."""
    gate = _FakeGate(
        agent_name="td_never_versioned",
        blocked=True,
        report=_FakeReport(current_score=0.2, baseline_score=0.8, delta=-0.6),
    )
    mock_detector = MagicMock()
    mock_detector.check_fleet.return_value = [gate]

    mock_registry = MagicMock()
    mock_registry.get_deployed.return_value = None  # never versioned

    mock_db = AsyncMock()

    with (
        patch(
            "app.fleet.regression_detector.get_regression_detector",
            return_value=mock_detector,
        ),
        patch(
            "app.fleet.prompt_registry.get_prompt_registry", return_value=mock_registry
        ),
        patch(
            "app.db.session.get_session_factory",
            return_value=_factory_returning(mock_db),
        ),
    ):
        await _run_prompt_auto_rollback_once()

    mock_registry.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_skips_agent_not_currently_regressed() -> None:
    gate = _FakeGate(
        agent_name="td_healthy_agent",
        blocked=False,
        report=_FakeReport(current_score=0.9, baseline_score=0.9, delta=0.0),
    )
    mock_detector = MagicMock()
    mock_detector.check_fleet.return_value = [gate]
    mock_registry = MagicMock()

    with (
        patch(
            "app.fleet.regression_detector.get_regression_detector",
            return_value=mock_detector,
        ),
        patch(
            "app.fleet.prompt_registry.get_prompt_registry", return_value=mock_registry
        ),
    ):
        await _run_prompt_auto_rollback_once()

    mock_registry.get_deployed.assert_not_called()
    mock_registry.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_oscillation_guard_skips_within_cooldown() -> None:
    """A rollback within the last PROMPT_AUTO_ROLLBACK_COOLDOWN_HOURS for the
    same role must not fire again, even if still flagged as regressed —
    guards against the still-warming-ring-buffer thrash scenario."""
    from datetime import datetime, timezone

    gate = _FakeGate(
        agent_name="td_cooldown_agent",
        blocked=True,
        report=_FakeReport(current_score=0.3, baseline_score=0.9, delta=-0.6),
    )
    mock_detector = MagicMock()
    mock_detector.check_fleet.return_value = [gate]

    mock_registry = MagicMock()
    mock_registry.get_deployed.return_value = SimpleNamespace(id=2)

    mock_db = AsyncMock()
    recent = datetime.now(timezone.utc).isoformat()

    with (
        patch(
            "app.fleet.regression_detector.get_regression_detector",
            return_value=mock_detector,
        ),
        patch(
            "app.fleet.prompt_registry.get_prompt_registry", return_value=mock_registry
        ),
        patch(
            "app.db.session.get_session_factory",
            return_value=_factory_returning(mock_db),
        ),
        patch("app.db.repository.get_setting", new=AsyncMock(return_value=recent)),
        patch("app.db.repository.set_setting", new=AsyncMock()) as mock_set_setting,
    ):
        await _run_prompt_auto_rollback_once()

    mock_registry.rollback.assert_not_called()
    mock_set_setting.assert_not_called()


@pytest.mark.asyncio
async def test_no_baseline_yet_never_triggers_rollback() -> None:
    """regression_detector.check_fleet() reports blocked=False when
    baseline_score is None by design (build_regression_report's own
    contract) — this test guards the auto-rollback loop's own explicit
    double-check of that same invariant."""
    gate = _FakeGate(
        agent_name="td_no_baseline",
        blocked=False,
        report=_FakeReport(current_score=0.5, baseline_score=None, delta=0.0),
    )
    mock_detector = MagicMock()
    mock_detector.check_fleet.return_value = [gate]
    mock_registry = MagicMock()

    with (
        patch(
            "app.fleet.regression_detector.get_regression_detector",
            return_value=mock_detector,
        ),
        patch(
            "app.fleet.prompt_registry.get_prompt_registry", return_value=mock_registry
        ),
    ):
        await _run_prompt_auto_rollback_once()

    mock_registry.rollback.assert_not_called()
