"""Tests for MASTER_AGENT_v2.md Phase 3.2 — manager.py's real epic cost_actual.

Before this, `_run_epic_manager_body`'s cost_actual computation did a literal
`SELECT SUM(DevTask.id)` (summing primary keys — meaningless), discarded the
result unused (`# noqa: F841`), and fell back to `refined_estimate.
estimated_cost_usd` — the pre-run *estimate* — silently mislabeled as the
post-run "actual" cost. The real numbers were always computed by
base_graph.py's final_state per agent run; they were just discarded at each
dispatched agent's own return statement (backend_dev.py/frontend_dev.py
computed tokens for a log line then returned only 2 of the 4 relevant
values; qa.py/reviewer.py's dataclasses didn't carry token fields at all).

This file covers the pure cost formula (compute_actual_cost_usd) directly;
run_manager()'s real token accumulation across dispatched agents is covered
by tests/test_manager_git_commit.py (which already exercises run_manager()
against a real git worktree); a full end-to-end test of
_run_epic_manager_body's cost_actual write would need a real Postgres Epic
row (same local-sandbox limitation documented throughout this session's
other DB-integration tests).
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.agents.manager import compute_actual_cost_usd


def test_compute_actual_cost_usd_matches_real_config_rates() -> None:
    settings = SimpleNamespace(
        cost_per_input_token=0.0000008, cost_per_output_token=0.000004
    )
    cost = compute_actual_cost_usd(
        tokens_in=100_000, tokens_out=20_000, settings=settings
    )
    assert cost == round(100_000 * 0.0000008 + 20_000 * 0.000004, 6)


def test_compute_actual_cost_usd_zero_tokens_is_zero_cost() -> None:
    settings = SimpleNamespace(
        cost_per_input_token=0.0000008, cost_per_output_token=0.000004
    )
    assert compute_actual_cost_usd(0, 0, settings) == 0.0


def test_compute_actual_cost_usd_uses_real_default_settings() -> None:
    """Confirms the formula is wired to the same settings fields
    app/pipeline/cost_controller.py's own estimate_epic_cost() reads —
    not a hardcoded/duplicated rate."""
    from app.config import get_settings

    settings = get_settings()
    cost = compute_actual_cost_usd(1000, 500, settings)
    expected = round(
        1000 * settings.cost_per_input_token + 500 * settings.cost_per_output_token,
        6,
    )
    assert cost == expected


def test_run_epic_manager_body_no_longer_sums_dev_task_ids() -> None:
    """Regression guard for the exact bug this phase fixed: a literal
    `SELECT SUM(DevTask.id)` (summing primary keys, meaningless) must not
    reappear in manager.py."""
    import app.agents.manager as manager_mod

    source = inspect.getsource(manager_mod)
    assert "sqlfunc.sum(DevTask.id)" not in source
    assert "compute_actual_cost_usd" in source
