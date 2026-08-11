"""Tests for AUDIT_Q_BATCH15 §115 gap-closure — release retrospectives
(app/fleet/release_retrospective.py). generate_release_retrospective (the
DB-touching aggregator) is exercised via a mocked AsyncSession; the pure
formatting function is tested directly against real dataclass values.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.fleet.release_retrospective import (
    ReleaseRetrospective,
    format_retrospective_markdown,
    generate_release_retrospective,
)


def test_format_retrospective_markdown_includes_real_counts() -> None:
    r = ReleaseRetrospective(
        from_sha="a" * 40,
        to_sha="b" * 40,
        period_start="2026-08-01T00:00:00+00:00",
        tasks_completed=7,
        tasks_failed=2,
        tasks_blocked=1,
        tasks_cancelled=0,
        sample_failures=["#12 Fix flaky migration test"],
        enhancement_requests_approved=3,
        enhancement_requests_rejected=1,
        enhancement_requests_filed=4,
    )
    out = format_retrospective_markdown(r)

    assert "7 task(s) completed" in out
    assert "2 task(s) failed" in out
    assert "1 task(s) still blocked" in out
    assert "3 fleet self-improvement request(s) approved" in out
    assert "1 of 4 filed enhancement request(s) were rejected" in out
    assert "#12 Fix flaky migration test" in out
    assert r.to_sha[:12] in out


def test_format_retrospective_markdown_handles_zero_closed_tasks() -> None:
    r = ReleaseRetrospective(
        from_sha=None, to_sha="c" * 40, period_start="2026-08-01T00:00:00+00:00"
    )
    out = format_retrospective_markdown(r)
    assert "n/a" in out  # success rate undefined with 0 closed tasks
    assert "(none)" in out  # no from_sha on first-ever run


@pytest.mark.asyncio
async def test_generate_release_retrospective_counts_real_task_statuses() -> None:
    mock_db = AsyncMock()

    def _tasks(status: str) -> SimpleNamespace:
        return SimpleNamespace(id=1, title="t", status=status)

    task_scalars = MagicMock()
    task_scalars.all.return_value = [
        _tasks("completed"),
        _tasks("completed"),
        _tasks("failed"),
        _tasks("blocked"),
    ]
    task_result = MagicMock()
    task_result.scalars.return_value = task_scalars

    er_scalars = MagicMock()
    er_scalars.all.return_value = [
        SimpleNamespace(status="approved"),
        SimpleNamespace(status="rejected"),
    ]
    er_result = MagicMock()
    er_result.scalars.return_value = er_scalars

    mock_db.execute = AsyncMock(side_effect=[task_result, er_result])

    retro = await generate_release_retrospective(
        mock_db,
        repo_path="/tmp/does-not-matter",
        repo_id=None,
        from_sha=None,
        to_sha="d" * 40,
    )

    assert retro.tasks_completed == 2
    assert retro.tasks_failed == 1
    assert retro.tasks_blocked == 1
    assert retro.enhancement_requests_approved == 1
    assert retro.enhancement_requests_rejected == 1
    assert retro.enhancement_requests_filed == 2
