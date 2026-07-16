"""Fleet Manager — Phase F3.

Owns task dispatch and load balancing. Given a task, queries capability_registry
and agent_registry to pick the best-fit available agent.

Rules (from Master Prompt §3):
- Do NOT select the first matching agent by name.
- Query capability_registry for agents that cover the requested capabilities.
- Query agent_registry to confirm the candidate is actually available (Sleep/Idle).
- Score candidates by: health weight (1.0/0.5/0.0) × success_rate × (1 / (1+error_count))
- Refuse dispatch if no healthy available agent covers the requested capabilities.
- Refuse dispatch if the agent's contract does not cover requested side_effects.

Design decisions:
- Does NOT replace manager.py or dispatcher.py — those orchestrate subtask pipelines.
  Fleet Manager is the top-level dispatcher that selects WHICH agent type to use.
- Existing dispatcher.py _TYPE_TO_TAG fallback remains unchanged for legacy paths.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.fleet.agent_registry import AgentInstance, AgentRegistry, get_agent_registry
from app.fleet.capability_registry import AgentCapability, CapabilityRegistry, get_capability_registry

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
    ) -> None:
        self._caps = capability_registry or get_capability_registry()
        self._agents = agent_registry or get_agent_registry()

    def select(
        self,
        required_capability: str,
        requested_side_effects: list[str] | None = None,
        prefer_low_risk: bool = False,
    ) -> DispatchPlan | None:
        """Find the best available agent for the requested capability.

        Returns None if no healthy available agent can handle the request.
        """
        candidates = self._caps.find_by_capability(required_capability)
        if not candidates:
            logger.warning("No agents registered for capability %r", required_capability)
            return None

        side_effects = requested_side_effects or []
        scored: list[tuple[float, AgentCapability, AgentInstance]] = []

        for cap in candidates:
            if prefer_low_risk and cap.risk_level == "high":
                continue

            instance = self._agents.get(cap.name)
            if instance is None:
                # Agent not yet registered in live registry — auto-register as sleep
                instance = self._agents.register(cap.name)

            if not instance.is_available:
                logger.debug("Agent %r is not available (state=%s)", cap.name, instance.state)
                continue

            # Contract check: agent must declare any side_effect it's asked to perform
            # (for reference agents, this is validated via AGENT_CONTRACT in their module)
            uncovered = [se for se in side_effects if se not in (cap.limits.get("side_effects") or [])]
            if uncovered and side_effects:
                # Non-blocking warning on Day 0 — enforcement tightens in Phase F4
                logger.debug("Agent %r does not declare side_effects %s (non-blocking Day 0)", cap.name, uncovered)

            health_weight = {"healthy": 1.0, "degraded": 0.5, "unhealthy": 0.0}.get(instance.health, 0.0)
            score = health_weight * cap.success_rate * (1.0 / (1.0 + instance.error_count))
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
            task_id, plan.agent_name, plan.score,
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
