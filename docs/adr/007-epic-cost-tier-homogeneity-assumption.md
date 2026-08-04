# ADR 007 — Epic cost aggregation assumes homogeneous-tier contributors; must move to per-run tier accounting if that ever changes

**Status:** Accepted
**Date:** 2026-08-05

## Context

Stage 4 Cluster P (`65days_plan/STAGE4_BACKLOG.md`) found that every real cost computation in this
codebase — pre-run estimates (`app/pipeline/cost_controller.py::estimate_epic_cost`) and post-run
actuals (`app/agents/manager.py::compute_actual_cost_usd`, `app/fleet/metrics.py::RunMetrics`) — used
a single flat `cost_per_input_token`/`cost_per_output_token` pair mislabeled "Haiku pricing" for
every agent, regardless of `app/fleet/model_router.py`'s own real per-agent tier.

Before implementing a fix, the real execution paths were verified rather than assumed. That
verification found the fleet's cost surface splits into two genuinely different shapes:

- **Per-run cost** (`RunMetrics._recompute_cost()` in `app/fleet/metrics.py`) has a real
  `agent_name` for every run, and can — and now does — resolve `model_router.route(agent_name).tier`
  directly and price at that tier via the new `cost_rates_for_tier()` helper
  (`app/pipeline/cost_controller.py`).
- **Epic-wide aggregate cost** (`app/agents/manager.py::compute_actual_cost_usd`) is called with a
  single pre-summed `tokens_in`/`tokens_out` total, accumulated across exactly 4 dispatched agents —
  `backend_dev`, `frontend_dev`, `qa`, `reviewer`. All 4 are verified sonnet-tier in
  `agent_models.json` today (`run_manager()`'s dev-dispatch decision, `selected_agent_name`, only
  ever chooses between `backend_dev`/`frontend_dev`; `qa`/`reviewer` are fixed-identity calls). A
  single flat (now Sonnet) rate is therefore exactly correct for this aggregate today — not an
  approximation.

## Decision

`compute_actual_cost_usd()` keeps its current single-flat-rate formula. We are **not** building
per-tier token accumulation into `run_manager()`'s epic aggregation now, because there is no real
mixed-tier data to aggregate — doing so would be speculative infrastructure for a case that doesn't
exist, the same category of overreach this project's own engineering standards explicitly reject
("Don't design for hypothetical future requirements").

This decision is conditional, not permanent. `compute_actual_cost_usd()` carries an explicit
docstring invariant, and `tests/test_stage4_cluster_p_per_tier_cost.py::
test_manager_epic_tokens_contributors_are_all_sonnet_tier` is a standing regression guard: **if any
future change ever dispatches a non-sonnet-tier agent into `run_manager()`'s `epic_tokens_in`/
`epic_tokens_out` accumulation** (e.g. an opus-tier reviewer, a haiku-tier fast-path dev agent), that
test fails immediately, and `compute_actual_cost_usd()` must stop taking pre-summed flat totals and
instead accumulate cost **per contributing agent's own resolved tier** — summing
`tokens_in_at_tier * cost_rates_for_tier(tier, settings)[0] + tokens_out_at_tier * cost_rates_for_tier(tier, settings)[1]`
across each real dispatched agent, the same way `RunMetrics._recompute_cost()` already does per run.
The mechanical shape of that future change: replace the two scalar accumulators
(`epic_tokens_in`/`epic_tokens_out`) with a `dict[tier, (tokens_in, tokens_out)]` accumulator at each
of the 3 real accumulation points in `run_manager()` (dev dispatch, qa, reviewer), threaded through
`manager_result` to `_finalize_node`.

## Rationale

- **Verified, not assumed.** The homogeneous-tier fact was confirmed by reading `agent_models.json`
  and `run_manager()`'s real dispatch logic, not inferred from the original bug report's speculative
  framing (which assumed `model_router.route(agent_name).tier` should be "consulted" at cost-estimate
  time — verified false: no agent is chosen yet at either `estimate_epic_cost()` call site).
- **Separating missing infrastructure from missing aggregation.** The infrastructure for correct
  per-tier pricing (`cost_rates_for_tier()`) already exists and is already exercised by
  `RunMetrics`. What's absent is not pricing infrastructure — it's mixed-tier *data* to aggregate.
  Building aggregation machinery ahead of that data would be implementing around absent data, which
  this project's standing discipline treats as a defect pattern in its own right, not a
  future-proofing virtue.
- **A failing test is a better trigger than a comment alone.** A regression guard means this
  assumption cannot silently rot the way the original Haiku-rate bug did — any future PR that adds a
  non-sonnet agent into the epic-cost dispatch path gets a concrete, immediate signal, not a stale
  comment nobody rereads.

## Consequences

- Future contributors adding a new agent to `run_manager()`'s dev/qa/review dispatch path must check
  its `model_router.py` tier. If it is not sonnet, `test_manager_epic_tokens_contributors_are_all_sonnet_tier`
  will fail and `compute_actual_cost_usd()` must be migrated to per-tier accumulation as described
  above — not patched with a second flat constant.
- This ADR, together with `app/agents/manager.py::compute_actual_cost_usd`'s own docstring and
  `STAGE4_BACKLOG.md`'s Cluster P section, is the canonical reference for why epic cost aggregation
  is currently flat-rate and exactly what must change if that ever stops being true.
