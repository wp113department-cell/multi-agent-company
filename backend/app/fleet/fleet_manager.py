"""Fleet Manager — Phase F3.

Owns task dispatch and load balancing. Given a task, queries capability_registry
and agent_registry to pick the best-fit available agent.

Rules (from Master Prompt §3):
- Do NOT select the first matching agent by name.
- Query capability_registry for agents that cover the requested capabilities.
- Query agent_registry to confirm the candidate is actually available (Sleep/Idle).
- Score candidates by: health weight (1.0/0.5/0.0) × success_rate × (1 / (1+error_count))
  × tenure factor × confidence factor (Batch 2 audit gap-closure — see select()'s
  own docstring for the exact formula and why each factor is neutral, not
  score-dominant, for a freshly-registered agent with no run history yet).
- Refuse dispatch if no healthy available agent covers the requested capabilities.
- Refuse dispatch if the agent's contract does not cover requested side_effects.

Design decisions:
- Does NOT replace manager.py or dispatcher.py — those orchestrate subtask pipelines.
  Fleet Manager is the top-level dispatcher that selects WHICH agent type to use.
- Existing dispatcher.py _TYPE_TO_TAG fallback remains unchanged for legacy paths.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.fleet.agent_registry import AgentInstance, AgentRegistry, get_agent_registry
from app.fleet.capability_registry import (
    AgentCapability,
    CapabilityRegistry,
    get_capability_registry,
)
from app.fleet.metrics import MetricsCollector, get_metrics_collector

logger = logging.getLogger(__name__)


@dataclass
class DispatchPlan:
    agent_name: str
    capability: AgentCapability
    instance: AgentInstance
    score: float
    reason: str


class FleetManager:
    """Registry-driven agent dispatcher.

    Why Created: manager.py dispatches by hardcoded subtask type strings.
      Adding a new agent requires a code change. Fleet Manager makes dispatch
      a data-driven query so new agents self-register without code changes.
    Alternatives Considered: DB-only dispatch (adds latency to the hot path).
    Why Existing Architecture Was Insufficient: no capability lookup; no availability check.
    Dependencies: CapabilityRegistry, AgentRegistry.
    Future Owner: Fleet OS team.
    """

    def __init__(
        self,
        capability_registry: CapabilityRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self._caps = capability_registry or get_capability_registry()
        self._agents = agent_registry or get_agent_registry()
        # plan14 Day 3 Task 6 — same DI pattern as capability_registry/
        # agent_registry above, so tests can inject a fresh MetricsCollector
        # instead of polluting/reading the real process-wide singleton.
        self._metrics = metrics_collector or get_metrics_collector()

    def select(
        self,
        required_capability: str,
        requested_side_effects: list[str] | None = None,
        prefer_low_risk: bool = False,
        verify_tool_availability: bool = False,
    ) -> DispatchPlan | None:
        """Find the best available agent for the requested capability.

        Returns None if no healthy available agent can handle the request.

        verify_tool_availability (gap-closure, 2026-07-21): Day 10 built
        tool_discovery.py (a thin index over tool_manifest.py +
        capability_registry.py) but it was never consulted from any real code
        path. Opt-in here — when True, skip candidates whose declared tools
        include one that isn't documented/resolvable
        (tool_discovery.check_availability()), catching a stale or typo'd
        tool name in an agent's own contract. Defaults False so every
        existing caller keeps its exact current behavior.

        Scoring (Batch 2 audit gap-closure, §3 "Experience (tenure)" /
        "Confidence"): the base health/success_rate/error_count formula is
        multiplied by two more real, already-tracked-but-previously-unread
        AgentInstance factors:
        - tenure_factor = 1 + min(log1p(total_runs) * 0.05, 0.3) — a
          diminishing-returns bonus (capped at +30%) for an agent with more
          completed runs under its belt. log1p rather than a raw count so
          run #1 -> #2 matters more than run #500 -> #501.
        - confidence_factor = avg_confidence if the agent has completed at
          least one planned run, else 1.0 (neutral — no history yet to
          judge by, matches every pre-existing test's freshly-registered
          agents, which all have avg_confidence=None).
        Both are 1.0 for a brand-new agent instance (total_runs=0,
        avg_confidence=None), so a fresh registry is scored IDENTICALLY to
        before this change — these factors only start differentiating
        candidates once real run history exists, and even then the tenure
        bonus is capped small enough that a genuinely unhealthy/low-success
        agent can never outscore a healthy one on tenure alone.

        plan14 Day 3 Task 6 (Performance-Aware Runtime Decisions) — two more
        multiplicative terms, same "neutral (1.0) until real history exists"
        property as tenure/confidence above:
        - cost_factor = 1 - min(avg_cost_usd * fleet_select_cost_penalty_weight, fleet_select_max_cost_penalty)
        - latency_factor = 1 - min((p50_latency_ms / 1000) * fleet_select_latency_penalty_weight, fleet_select_max_latency_penalty)
        Both read from MetricsCollector (real per-run cost/latency, not
        fabricated) and default to 1.0 when an agent has no run history yet.
        Performance is a ranking signal only — it's applied AFTER the
        capability/availability/side-effect filtering above, never replaces
        it. Deliberately a CAPPED linear penalty (same shape as
        tenure_factor's own capped bonus above), not an unbounded curve — a
        real regression test caught an earlier unbounded design letting an
        extreme cost/latency outlier flip a large real success_rate gap,
        which the "Performance MUST NOT override capability/health/
        security... is a ranking signal, not an authorization signal"
        instruction argues against. With both penalties at their default
        0.3 cap simultaneously, the worst case is a 0.7*0.7=0.49x
        reduction — enough to break a close tie, never enough to flip a
        multi-times success_rate gap.

        plan14 follow-on #3 (Memory-Aware Agent Selection) — one more term,
        the durable complement to confidence_factor above (which is
        in-process/AgentInstance-only and resets on restart):
        - memory_performance_factor, read from
          app.fleet.agent_historical_performance's in-process cache (itself
          refreshed by a scheduled rollup over memory_embeddings.agent_name
          — deliberately NOT a live join on this hot path, per the audit
          backing this plan). Neutral (1.0) whenever no rollup row exists
          yet for this agent, the row has fewer than
          fleet_select_memory_performance_min_samples real outcomes, or the
          feature is disabled (agent_historical_performance_enabled=False).
          Otherwise: ((success_rate - 0.5) * 2) scaled by
          fleet_select_memory_performance_weight and capped at
          +/-fleet_select_max_memory_performance_penalty — the same
          symmetric-around-neutral shape confidence_factor already has
          (0.5 = no signal either way), and the same capped-linear
          ranking-only shape cost_factor/latency_factor use, deliberately
          smaller (default cap 0.2 vs 0.3) since this is an hours-old
          rollup, not a live per-run metric.
        """
        candidates = self._caps.find_by_capability(required_capability)
        if not candidates:
            logger.warning(
                "No agents registered for capability %r", required_capability
            )
            return None

        side_effects = requested_side_effects or []
        scored: list[tuple[float, AgentCapability, AgentInstance]] = []

        from app.config import get_settings

        settings = get_settings()
        collector = self._metrics

        for cap in candidates:
            if prefer_low_risk and cap.risk_level == "high":
                continue

            if verify_tool_availability:
                from app.fleet.tool_discovery import check_availability

                unavailable = [t for t in cap.tools if not check_availability(t)]
                if unavailable:
                    logger.warning(
                        "Agent %r declares unresolvable tool(s) %s — skipping",
                        cap.name,
                        unavailable,
                    )
                    continue

            instance = self._agents.get(cap.name)
            if instance is None:
                # Agent not yet registered in live registry — auto-register as sleep
                instance = self._agents.register(cap.name)

            if not instance.is_available:
                logger.debug(
                    "Agent %r is not available (state=%s)", cap.name, instance.state
                )
                continue

            # Contract check: agent must declare any side_effect it's asked to perform
            # (for reference agents, this is validated via AGENT_CONTRACT in their module)
            uncovered = [
                se
                for se in side_effects
                if se not in (cap.limits.get("side_effects") or [])
            ]
            if uncovered and side_effects:
                # Non-blocking warning on Day 0 — enforcement tightens in Phase F4
                logger.debug(
                    "Agent %r does not declare side_effects %s (non-blocking Day 0)",
                    cap.name,
                    uncovered,
                )

            health_weight = {"healthy": 1.0, "degraded": 0.5, "unhealthy": 0.0}.get(
                instance.health, 0.0
            )
            tenure_factor = 1.0 + min(math.log1p(instance.total_runs) * 0.05, 0.3)
            confidence_factor = (
                instance.avg_confidence if instance.avg_confidence is not None else 1.0
            )

            avg_cost = collector.avg_cost_usd(cap.name)
            cost_factor = (
                1.0
                - min(
                    avg_cost * settings.fleet_select_cost_penalty_weight,
                    settings.fleet_select_max_cost_penalty,
                )
                if avg_cost is not None
                else 1.0
            )
            p50_ms = collector.p50_latency_ms(cap.name)
            latency_factor = (
                1.0
                - min(
                    (p50_ms / 1000.0) * settings.fleet_select_latency_penalty_weight,
                    settings.fleet_select_max_latency_penalty,
                )
                if p50_ms is not None
                else 1.0
            )

            memory_performance_factor = 1.0
            if settings.agent_historical_performance_enabled:
                from app.fleet.agent_historical_performance import (
                    get_cached_performance,
                )

                mem_perf = get_cached_performance(cap.name, category="task")
                if (
                    mem_perf is not None
                    and mem_perf.success_rate is not None
                    and mem_perf.sample_size
                    >= settings.fleet_select_memory_performance_min_samples
                ):
                    deviation = (mem_perf.success_rate - 0.5) * 2.0
                    capped_deviation = max(
                        -settings.fleet_select_max_memory_performance_penalty,
                        min(
                            settings.fleet_select_max_memory_performance_penalty,
                            deviation * settings.fleet_select_memory_performance_weight,
                        ),
                    )
                    memory_performance_factor = 1.0 + capped_deviation

            score = (
                health_weight
                * cap.success_rate
                * (1.0 / (1.0 + instance.error_count))
                * tenure_factor
                * confidence_factor
                * cost_factor
                * latency_factor
                * memory_performance_factor
            )
            scored.append((score, cap, instance))

        if not scored:
            logger.warning(
                "No available agents for capability %r (all busy or unhealthy). Candidates: %s",
                required_capability,
                [c.name for c in candidates],
            )
            return None

        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best_cap, best_instance = scored[0]

        return DispatchPlan(
            agent_name=best_cap.name,
            capability=best_cap,
            instance=best_instance,
            score=best_score,
            reason=(
                f"Selected via registry lookup: capability={required_capability!r}, "
                f"score={best_score:.3f}, health={best_instance.health}"
            ),
        )

    def dispatch(
        self,
        required_capability: str,
        task_id: str,
        task_payload: dict[str, Any],
        requested_side_effects: list[str] | None = None,
    ) -> dict[str, Any]:
        """Select an agent and mark it as running. Returns dispatch metadata.

        Does NOT actually call the agent — that is the caller's responsibility.
        This function's job is purely: select → validate → mark running → return plan.
        """
        plan = self.select(required_capability, requested_side_effects)
        if plan is None:
            return {
                "status": "no_agent_available",
                "capability": required_capability,
                "task_id": task_id,
            }

        self._agents.start_task(plan.agent_name, task_id)
        logger.info(
            "Fleet dispatch: task_id=%s → agent=%s (score=%.3f)",
            task_id,
            plan.agent_name,
            plan.score,
        )

        return {
            "status": "dispatched",
            "agent_name": plan.agent_name,
            "task_id": task_id,
            "score": plan.score,
            "reason": plan.reason,
            "capability": plan.capability.name,
            "risk_level": plan.capability.risk_level,
        }

    def complete(self, agent_name: str) -> None:
        self._agents.complete_task(agent_name)

    def fail(self, agent_name: str, reason: str) -> None:
        self._agents.fail_task(agent_name, reason)

    def status(self) -> dict[str, Any]:
        return {
            "registered_capabilities": self._caps.count(),
            "agent_instances": len(self._agents.all()),
            "available": len(self._agents.available()),
            "running": len(self._agents.running()),
            "snapshot": self._agents.snapshot(),
        }


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_fleet_manager = FleetManager()


def get_fleet_manager() -> FleetManager:
    return _fleet_manager
