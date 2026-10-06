"""Background fleet scans never use up the owner's daily budget (audit 15)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import get_settings
from app.main import _fleet_scan_budget_exhausted


@pytest.mark.parametrize(
    ("spent", "skipped"), [(0.0, False), (0.49, False), (0.5, True), (0.9, True)]
)
def test_scans_stop_once_their_share_of_the_cap_is_used(
    monkeypatch: pytest.MonkeyPatch, spent: float, skipped: bool
) -> None:
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 1.0)
    monkeypatch.setattr(get_settings(), "fleet_scan_budget_fraction", 0.5)
    with patch("app.fleet.spend_guard.spent_today", return_value=spent):
        assert _fleet_scan_budget_exhausted("agent_debugger") is skipped


def test_no_cap_means_no_skipping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 0.0)
    with patch("app.fleet.spend_guard.spent_today", return_value=99.0):
        assert _fleet_scan_budget_exhausted("agent_debugger") is False


def test_scans_are_daily_by_default() -> None:
    from app.config import Settings

    assert Settings.model_fields["fleet_scan_interval_hours"].default == 24.0
