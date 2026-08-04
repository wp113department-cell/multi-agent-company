"""Stage 4 Cluster P (2026-08-05, STAGE4_BACKLOG.md) — cost tracking used a
single flat rate (labeled "Haiku pricing" in app/config.py) for every agent's
tokens, regardless of the agent's real model_router.py tier. 62 of 73
registered agents route to Sonnet and 9 to Opus (agent_models.json) — the
overwhelming majority of real fleet cost was silently computed at the wrong,
cheaper rate.

Real fix, verified against the actual codebase (not assumed):
  - app/config.py: cost_per_input_token/cost_per_output_token are now the
    real Sonnet-tier rate (was mislabeled "Haiku pricing" at a stale/wrong
    value); dedicated *_haiku / *_opus fields added.
  - app/pipeline/cost_controller.cost_rates_for_tier(tier, settings) is the
    single tier-aware lookup, falling back to the sonnet/default rate for
    any unrecognized tier (mirrors ModelRouter.route()'s own
    fallback-to-sonnet behavior for unregistered agent names).
  - app/fleet/metrics.py's RunMetrics._recompute_cost() now resolves the
    real tier via model_router.route(self.agent_name).tier before pricing
    — this is the per-run call site that has a real agent_name to resolve.
  - app/agents/manager.py's compute_actual_cost_usd() was verified NOT to
    need per-tier plumbing: the only 4 agents whose tokens ever feed its
    epic-wide tokens_in/tokens_out (backend_dev, frontend_dev, qa,
    reviewer) are all sonnet-tier today (agent_models.json) — so the
    corrected flat Sonnet rate is already exactly correct there. Test
    below is the regression guard that keeps that invariant honest.
"""

from __future__ import annotations

from app.agents.manager import compute_actual_cost_usd
from app.config import get_settings
from app.fleet.metrics import RunMetrics
from app.fleet.model_router import get_model_router
from app.pipeline.cost_controller import cost_rates_for_tier


def test_cost_rates_for_tier_haiku() -> None:
    s = get_settings()
    assert cost_rates_for_tier("haiku", s) == (
        s.cost_per_input_token_haiku,
        s.cost_per_output_token_haiku,
    )


def test_cost_rates_for_tier_opus() -> None:
    s = get_settings()
    assert cost_rates_for_tier("opus", s) == (
        s.cost_per_input_token_opus,
        s.cost_per_output_token_opus,
    )


def test_cost_rates_for_tier_sonnet() -> None:
    s = get_settings()
    assert cost_rates_for_tier("sonnet", s) == (
        s.cost_per_input_token,
        s.cost_per_output_token,
    )


def test_cost_rates_for_tier_unknown_falls_back_to_sonnet_default() -> None:
    """Mirrors ModelRouter.route()'s own fallback-to-sonnet for unrecognized
    tiers — includes "gpt", which has zero registered agents today."""
    s = get_settings()
    for tier in ("gpt", "totally-unknown-tier", ""):
        assert cost_rates_for_tier(tier, s) == (
            s.cost_per_input_token,
            s.cost_per_output_token,
        )


def test_haiku_rate_is_cheaper_than_sonnet_and_sonnet_cheaper_than_opus() -> None:
    """Sanity check on the real sourced pricing: haiku < sonnet < opus, both
    input and output — catches a transposed/typo'd config value."""
    s = get_settings()
    assert s.cost_per_input_token_haiku < s.cost_per_input_token
    assert s.cost_per_input_token < s.cost_per_input_token_opus
    assert s.cost_per_output_token_haiku < s.cost_per_output_token
    assert s.cost_per_output_token < s.cost_per_output_token_opus


def test_run_metrics_recompute_cost_uses_opus_rate_for_architect() -> None:
    """architect is opus-tier per agent_models.json — this is the real
    end-to-end proof that RunMetrics now consults the real per-run tier
    instead of a single flat rate."""
    s = get_settings()
    tier = get_model_router().route("architect").tier
    assert tier == "opus"

    m = RunMetrics(trace_id="t-cluster-p-1", agent_name="architect")
    m.record_tokens(100_000, 20_000)

    expected = 100_000 * s.cost_per_input_token_opus + 20_000 * s.cost_per_output_token_opus
    assert m.cost_estimate_usd == expected
    # The old bug: applying the flat (pre-fix) Haiku rate would have been
    # cheaper than the real opus cost — prove the fix actually changed the
    # number, not just re-derived the same value under a new name.
    old_flat_haiku_cost = 100_000 * 0.0000008 + 20_000 * 0.000004
    assert m.cost_estimate_usd > old_flat_haiku_cost


def test_run_metrics_recompute_cost_uses_haiku_rate_for_env_checker_agent() -> None:
    """env_checker_agent is haiku-tier per agent_models.json."""
    s = get_settings()
    tier = get_model_router().route("env_checker_agent").tier
    assert tier == "haiku"

    m = RunMetrics(trace_id="t-cluster-p-2", agent_name="env_checker_agent")
    m.record_tokens(50_000, 10_000)

    expected = (
        50_000 * s.cost_per_input_token_haiku + 10_000 * s.cost_per_output_token_haiku
    )
    assert m.cost_estimate_usd == expected


def test_run_metrics_recompute_cost_uses_sonnet_rate_for_backend_dev() -> None:
    s = get_settings()
    tier = get_model_router().route("backend_dev").tier
    assert tier == "sonnet"

    m = RunMetrics(trace_id="t-cluster-p-3", agent_name="backend_dev")
    m.record_tokens(80_000, 15_000)

    expected = 80_000 * s.cost_per_input_token + 15_000 * s.cost_per_output_token
    assert m.cost_estimate_usd == expected


def test_run_metrics_recompute_cost_unregistered_agent_falls_back_to_sonnet() -> None:
    """An agent_name not present in agent_models.json resolves through
    ModelRouter's own DEFAULT entry (tier="sonnet") — never raises, never
    silently drops cost tracking to zero."""
    s = get_settings()
    m = RunMetrics(trace_id="t-cluster-p-4", agent_name="not-a-real-agent-xyz")
    m.record_tokens(1_000, 200)

    expected = 1_000 * s.cost_per_input_token + 200 * s.cost_per_output_token
    assert m.cost_estimate_usd == expected


def test_manager_epic_tokens_contributors_are_all_sonnet_tier() -> None:
    """Regression guard for compute_actual_cost_usd's documented invariant:
    every agent whose tokens ever feed run_manager()'s epic_tokens_in/
    epic_tokens_out (backend_dev, frontend_dev, qa, reviewer) must stay
    sonnet-tier, or compute_actual_cost_usd's flat-rate formula silently
    becomes wrong again — the exact bug this cluster fixed. If this test
    ever fails, compute_actual_cost_usd must be changed to accumulate cost
    per-tier via cost_rates_for_tier() instead of a single flat rate."""
    router = get_model_router()
    for agent_name in ("backend_dev", "frontend_dev", "qa", "reviewer"):
        assert router.route(agent_name).tier == "sonnet", (
            f"{agent_name} is no longer sonnet-tier — compute_actual_cost_usd "
            "in app/agents/manager.py must be updated to per-tier accumulation"
        )


def test_compute_actual_cost_usd_now_uses_real_sonnet_rate_not_stale_haiku() -> None:
    """The core Cluster P regression guard: the settings object
    compute_actual_cost_usd() reads from must no longer carry the stale,
    mislabeled "Haiku pricing" default values."""
    s = get_settings()
    assert s.cost_per_input_token != 0.0000008
    assert s.cost_per_output_token != 0.000004

    cost = compute_actual_cost_usd(tokens_in=100_000, tokens_out=20_000, settings=s)
    expected = round(
        100_000 * s.cost_per_input_token + 20_000 * s.cost_per_output_token, 6
    )
    assert cost == expected
