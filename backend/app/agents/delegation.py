"""Agent-to-Agent Delegation — plan14 Day 4 (#1 + #13 + #12, built as one unit).

Confirmed fully absent before this (repo-wide grep, zero hits): no
delegate_to_agent, no cycle detection, no depth limit, no caller matrix
anywhere. All invocation previously ran top-down only, through
manager.py/fleet_manager.py.

Design, grounded in two concrete reference patterns (per the governing
5-day spec):
- Routing: a parent requests a CAPABILITY, never a hardcoded target agent
  name — app.fleet.fleet_manager.FleetManager.select() (already enhanced
  by plan14 Day 3 Task 6 with real performance-aware scoring) resolves the
  concrete agent, mirroring LangGraph's Command(goto=...) "the node decides
  where to go next" shape without inventing a second routing mechanism.
- Safety: AutoGen's Swarm pattern validates a handoff target against an
  explicit participant/allowed-matrix before permitting it. Depth/cycle
  protection mirrors LangGraph's own recursion_limit backstop.
- Communication: extends the EXISTING GridironEvent envelope
  (app/event_bus/models.py) with receiver/message_type/trace_id/
  parent_run_id fields rather than building a second, competing
  AgentId/envelope schema (AutoGen's separate AgentMessage type was
  considered and rejected for exactly that reason).

Real invocation is deliberately scoped to a small, curated adapter registry
(_build_adapter_registry), not all ~86 agents: most agent run_* functions
have bespoke, pipeline-specific signatures (e.g. run_qa needs
subtask_id/files_changed/worktree_path — it is not a general-purpose
delegation target at all). The four adapters here (spike_agent,
security_reviewer, code_explainer_agent, bug_fix) share a real, verified
compatible shape: (task_id: int, <objective>, repo_path=None, ...) ->
AgentResult. Expanding the registry — and delegation_allowed_matrix in
config.py — to more agents is additive, not a redesign.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.agent_result import AgentResult

logger = logging.getLogger(__name__)


class DelegationError(Exception):
    """Base class for every delegation refusal/failure. Never lets a
    delegation attempt raise an unstructured exception to the parent —
    every real caller (the delegate_to_agent tool handler) catches this
    and returns a structured failure instead."""


class DelegationDisabledError(DelegationError):
    pass


class DelegationDepthExceededError(DelegationError):
    pass


class DelegationCycleError(DelegationError):
    pass


class DelegationNotAllowedError(DelegationError):
    pass


class DelegationBudgetExceededError(DelegationError):
    pass


class DelegationTargetUnavailableError(DelegationError):
    pass


class DelegationTimeoutError(DelegationError):
    pass


@dataclass(frozen=True)
class DelegationRequest:
    """parent_agent/target_capability/objective/context/priority/budget/
    deadline/delegation_depth per the governing spec's own conceptual
    contract, plus ancestry (needed for real cycle detection — a plain
    depth counter alone cannot distinguish A->B->C->A from A->B->C->D)."""

    source_agent: str
    target_capability: str
    objective: str
    context: str
    ancestry: tuple[str, ...]
    delegation_depth: int
    budget_remaining_usd: float
    task_id: str = ""
    repo_path: str = ""
    trace_id: str = ""
    parent_run_id: str = ""


@dataclass(frozen=True)
class DelegationResult:
    success: bool
    target_agent: str | None
    result: AgentResult | None
    error: str | None
    cost_usd: float
    child_ancestry: tuple[str, ...] = field(default_factory=tuple)


def _build_adapter_registry() -> dict[str, Callable[[int, str, str], AgentResult]]:
    """Lazily imports each target agent's real run_*() function — deferred
    so importing this module doesn't eagerly pull in the whole agent
    package. Every adapter's signature is (task_id, objective, repo_path)
    -> AgentResult, real functions, real execution — never a mock or a
    fabricated result."""
    from app.agents.bug_fix import run_bug_fix
    from app.agents.code_explainer_agent import run_code_explainer_agent
    from app.agents.security_reviewer import run_security_review
    from app.agents.spike_agent import run_spike_agent

    return {
        "spike_agent": lambda task_id, objective, repo_path: run_spike_agent(
            task_id=task_id, description=objective, repo_path=repo_path or None
        ),
        "security_reviewer": lambda task_id, objective, repo_path: run_security_review(
            task_id=task_id, focus=objective, repo_path=repo_path or None
        ),
        "code_explainer_agent": lambda task_id, objective, repo_path: (
            run_code_explainer_agent(
                task_id=task_id, description=objective, repo_path=repo_path or None
            )
        ),
        "bug_fix": lambda task_id, objective, repo_path: run_bug_fix(
            task_id=task_id, error_description=objective, repo_path=repo_path or None
        ),
    }


def _publish_delegation_event(event: Any) -> None:
    """Sync-safe publish, reusing the exact cross-thread-safe pattern
    app.fleet.fleet_events.FleetBus already established for this same
    problem (a sync call site — here, delegate() itself, potentially
    called from a sync tool handler — publishing an event whose real
    persistence path, event_bus.bus.publish_event, is async). Best-effort:
    a publish failure must never break the actual delegation."""
    try:
        import asyncio

        from app.event_bus.bus import publish_event
        from app.fleet.fleet_events import get_main_loop

        loop = get_main_loop()
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(publish_event(event), loop)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return
        running.create_task(publish_event(event))
    except Exception:
        logger.debug("Delegation event publish failed (non-fatal)", exc_info=True)


def _audit_delegation(
    action_type: str, agent_name: str, description: str, **kwargs: Any
) -> None:
    try:
        from app.fleet.audit_log import audit

        audit(action_type, agent_name, description, **kwargs)
    except Exception:
        logger.debug("Delegation audit log failed (non-fatal)", exc_info=True)


def delegate(request: DelegationRequest) -> DelegationResult:
    """The one real entry point every delegation attempt goes through.
    Validates depth -> cycle -> policy -> budget -> resolves a target agent
    via FleetManager.select() (capability-based, never a hardcoded agent
    name) -> invokes it with a bounded timeout -> returns a structured
    result. Raises a DelegationError subclass on any guard failure — never
    silently proceeds and never fabricates a successful result on failure.
    """
    from app.config import get_settings

    settings = get_settings()

    if not settings.delegation_enabled:
        raise DelegationDisabledError(
            "Delegation is disabled (delegation_enabled=false)"
        )

    if request.delegation_depth >= settings.delegation_max_depth:
        raise DelegationDepthExceededError(
            f"Delegation depth {request.delegation_depth} >= max "
            f"{settings.delegation_max_depth} (ancestry: {list(request.ancestry)})"
        )

    if len(request.ancestry) > settings.delegation_max_delegations_per_run:
        raise DelegationBudgetExceededError(
            f"Delegation chain already has {len(request.ancestry)} hops, "
            f"exceeding delegation_max_delegations_per_run="
            f"{settings.delegation_max_delegations_per_run}"
        )

    if request.budget_remaining_usd <= 0:
        raise DelegationBudgetExceededError(
            f"No budget remaining for delegation from {request.source_agent!r} "
            f"(budget_remaining_usd={request.budget_remaining_usd})"
        )

    allowed_targets = settings.delegation_allowed_matrix.get(request.source_agent, [])
    if request.target_capability not in allowed_targets:
        raise DelegationNotAllowedError(
            f"{request.source_agent!r} is not allowed to delegate to capability "
            f"{request.target_capability!r} (allowed: {allowed_targets})"
        )

    from app.event_bus.models import (
        delegation_completed,
        delegation_failed,
        delegation_requested,
    )
    from app.fleet.fleet_manager import get_fleet_manager

    plan = get_fleet_manager().select(request.target_capability)
    if plan is None:
        raise DelegationTargetUnavailableError(
            f"No available agent covers capability {request.target_capability!r}"
        )
    target_agent_name = plan.agent_name

    # Cycle check: the resolved TARGET must not already be an ancestor in
    # this delegation chain (A -> B -> C -> A). Checked against the real
    # resolved agent name, not the requested capability — a capability can
    # resolve to a different concrete agent over time as availability/
    # performance changes, but the actual cycle risk is a specific agent
    # instance re-entering its own ancestry.
    if target_agent_name in request.ancestry:
        raise DelegationCycleError(
            f"Delegating to {target_agent_name!r} would create a cycle "
            f"(ancestry: {list(request.ancestry)})"
        )

    adapters = _build_adapter_registry()
    adapter = adapters.get(target_agent_name)
    if adapter is None:
        raise DelegationTargetUnavailableError(
            f"{target_agent_name!r} was resolved for capability "
            f"{request.target_capability!r} but has no real delegation adapter "
            f"registered (adapter registry: {sorted(adapters)})"
        )

    trace_id = request.trace_id or request.task_id or "delegation"
    _publish_delegation_event(
        delegation_requested(
            source_agent=request.source_agent,
            target_capability=request.target_capability,
            trace_id=trace_id,
            parent_run_id=request.parent_run_id,
            task_id=request.task_id or None,
        )
    )
    _audit_delegation(
        "delegation_requested",
        request.source_agent,
        f"Delegating to capability={request.target_capability!r} "
        f"(resolved={target_agent_name!r})",
        task_id=request.task_id or None,
        details={
            "target_capability": request.target_capability,
            "target_agent": target_agent_name,
            "depth": request.delegation_depth,
            "ancestry": list(request.ancestry),
        },
    )

    child_ancestry = (*request.ancestry, target_agent_name)

    try:
        task_id_int = int(request.task_id) if request.task_id.isdigit() else 0
        result = _run_with_timeout(
            lambda: adapter(task_id_int, request.objective, request.repo_path),
            settings.delegation_default_timeout_seconds,
        )
    except DelegationTimeoutError as exc:
        _publish_delegation_event(
            delegation_failed(
                source_agent=request.source_agent,
                target_agent=target_agent_name,
                trace_id=trace_id,
                parent_run_id=request.parent_run_id,
                reason=str(exc),
                task_id=request.task_id or None,
            )
        )
        _audit_delegation(
            "delegation_failed",
            request.source_agent,
            f"Delegation to {target_agent_name!r} timed out: {exc}",
            task_id=request.task_id or None,
        )
        return DelegationResult(
            success=False,
            target_agent=target_agent_name,
            result=None,
            error=str(exc),
            cost_usd=0.0,
            child_ancestry=child_ancestry,
        )
    except Exception as exc:
        # A child agent's own failure must return a structured failure to
        # the parent — never fabricate a successful delegation result, and
        # never let the child's exception propagate unstructured.
        logger.warning(
            "Delegation to %s (capability=%s) failed: %s",
            target_agent_name,
            request.target_capability,
            exc,
        )
        _publish_delegation_event(
            delegation_failed(
                source_agent=request.source_agent,
                target_agent=target_agent_name,
                trace_id=trace_id,
                parent_run_id=request.parent_run_id,
                reason=str(exc),
                task_id=request.task_id or None,
            )
        )
        _audit_delegation(
            "delegation_failed",
            request.source_agent,
            f"Delegation to {target_agent_name!r} raised: {exc}",
            task_id=request.task_id or None,
        )
        return DelegationResult(
            success=False,
            target_agent=target_agent_name,
            result=None,
            error=str(exc),
            cost_usd=0.0,
            child_ancestry=child_ancestry,
        )

    cost_usd = _estimate_result_cost_usd(target_agent_name)

    _publish_delegation_event(
        delegation_completed(
            source_agent=request.source_agent,
            target_agent=target_agent_name,
            trace_id=trace_id,
            parent_run_id=request.parent_run_id,
            cost_usd=cost_usd,
            task_id=request.task_id or None,
        )
    )
    _audit_delegation(
        "delegation_completed",
        request.source_agent,
        f"Delegation to {target_agent_name!r} completed (status={result.status!r})",
        task_id=request.task_id or None,
        details={"cost_usd": cost_usd, "status": result.status},
    )

    return DelegationResult(
        success=True,
        target_agent=target_agent_name,
        result=result,
        error=None,
        cost_usd=cost_usd,
        child_ancestry=child_ancestry,
    )


def _estimate_result_cost_usd(target_agent_name: str) -> float:
    """Best-effort real cost read from MetricsCollector's most recent run
    for the target agent (populated by run_agent_graph's own metrics span,
    which every real adapter call goes through) — falls back to 0.0 rather
    than fabricating a number if no metrics were recorded."""
    try:
        from app.fleet.metrics import get_metrics_collector

        runs = get_metrics_collector().by_agent(target_agent_name, n=1)
        return runs[-1].cost_estimate_usd if runs else 0.0
    except Exception:
        return 0.0


def _run_with_timeout(
    fn: Callable[[], AgentResult], timeout_seconds: float
) -> AgentResult:
    """Bounded timeout around a real (synchronous, blocking) agent
    invocation. Uses a worker thread + join(timeout) rather than a signal-
    based alarm — signals only work on the main thread, and delegation can
    be invoked from a worker thread (tool handlers already run inside
    run_agent_graph's own execution, which may itself be dispatched via
    asyncio.to_thread). Does not (and cannot, for a plain thread) forcibly
    kill a still-running child call past the timeout — it stops WAITING
    for it and reports a timeout to the parent; the thread is daemonized so
    it cannot keep the process alive."""
    import threading

    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            outcome["result"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised on the caller's thread
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    start = time.monotonic()
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        raise DelegationTimeoutError(
            f"Delegated agent call exceeded {timeout_seconds}s timeout "
            f"(still running after {time.monotonic() - start:.1f}s)"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]  # type: ignore[no-any-return]
