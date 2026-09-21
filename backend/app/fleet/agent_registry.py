"""Agent Registry — Phase F2.

Live registry of agent instances: health, current task, idle/Sleep state, availability.

Distinguishes "done and idle" from "still running" via the explicit Sleep state.
Fleet Manager queries this before assigning a task so it never dispatches to a
running or unhealthy agent.

Design decisions:
- In-process for Day 0 — complements the DB-backed api/registry.py (which stores
  historical metrics) without replacing it.
- Thread-safe via per-instance RLock.
- AgentState.SLEEP is the canonical "available, waiting for work" state; IDLE is
  transient between task completion and explicit sleep() call.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    IDLE = "idle"
    SLEEP = "sleep"
    RUNNING = "running"
    ERROR = "error"
    # AUDIT_Q_BATCH14 §77/§94 gap-closure (2026-08-12) — "Agent lifecycle
    # (hire/retire/replace/promote)" was NO: this enum had no state an
    # operator could put an agent into deliberately, distinct from the
    # health-driven "unhealthy" tier (which is a symptom the agent itself
    # produced via repeated failures, not a governance decision a human/
    # policy made about it). DISABLED is reversible (reactivate());
    # RETIRED is a deliberate, permanent-until-replaced governance decision
    # — matching AgentRegistry.disable/retire/reactivate below.
    DISABLED = "disabled"
    RETIRED = "retired"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentInstance:
    name: str
    state: AgentState = AgentState.SLEEP
    current_task_id: str | None = None
    last_active: datetime = field(default_factory=_now)
    health: str = "healthy"
    error_count: int = 0
    total_runs: int = 0
    # Gap-closure (Batch 2 audit, §3 "Confidence"): the planner's own
    # self-reported confidence (base_graph.py's `state["confidence"]`,
    # 0.0-1.0) from this agent's most recent completed runs, as an
    # exponential moving average — real per-run data that already existed
    # and already gated a post-hoc quality check, but was never carried
    # forward into anything FleetManager.select() could read. None until
    # this agent has completed at least one run through run_agent_graph()
    # with planning enabled (matches every real backend_dev/frontend_dev
    # call — see base_graph.py's complete_task() call site).
    avg_confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return (
            self.state in (AgentState.SLEEP, AgentState.IDLE)
            and self.health != "unhealthy"
        )

    def start(self, task_id: str) -> None:
        self.state = AgentState.RUNNING
        self.current_task_id = task_id
        self.last_active = _now()
        self.total_runs += 1

    def complete(self, confidence: float | None = None) -> None:
        self.state = AgentState.SLEEP
        self.current_task_id = None
        self.last_active = _now()
        if confidence is not None:
            # EMA (alpha=0.3): weights recent runs more than old ones
            # without a single bad/good run swinging the average wildly —
            # same smoothing rationale as success_rate's own accumulation
            # elsewhere in the fleet layer.
            self.avg_confidence = (
                confidence
                if self.avg_confidence is None
                else (0.3 * confidence + 0.7 * self.avg_confidence)
            )

    def fail(self, reason: str) -> None:
        self.state = AgentState.ERROR
        self.current_task_id = None
        self.last_active = _now()
        self.error_count += 1
        self.metadata["last_error"] = reason
        # AUDIT_Q_BATCH16 §88 gap-closure (2026-08-11) — "degraded" was a
        # real value in FleetManager.select()'s own health_weight dict
        # (fleet_manager.py: {"healthy": 1.0, "degraded": 0.5, "unhealthy":
        # 0.0}) but this method — the only place health is ever assigned —
        # only ever wrote "healthy" (the dataclass default) or "unhealthy"
        # (the >=3 branch below), so health_weight's 0.5 middle tier could
        # never actually be selected; confirmed by grepping every write to
        # `self.health` in this file before this change. 1-2 consecutive
        # errors is exactly the "3 consecutive errors" threshold's own
        # implied middle state, so this is the minimal fix that makes the
        # existing type/scoring system's own "degraded" tier reachable
        # without changing the >=3 -> unhealthy exclusion threshold
        # FleetManager.select()/is_available already rely on.
        if self.error_count >= 3:
            self.health = "unhealthy"
        else:
            self.health = "degraded"

    def sleep(self) -> None:
        self.state = AgentState.SLEEP
        self.current_task_id = None

    def recover(self) -> None:
        self.state = AgentState.SLEEP
        self.error_count = 0
        self.health = "healthy"

    def disable(self, reason: str) -> None:
        """Reversible administrative pause — is_available becomes False
        immediately (same exclusion FleetManager.select() already applies
        to RUNNING/ERROR), current work is left alone (a running task isn't
        interrupted), but no *new* dispatch will select this agent until
        reactivate()."""
        self.state = AgentState.DISABLED
        self.metadata["disabled_reason"] = reason
        self.metadata["disabled_at"] = _now().isoformat()

    def retire(self, reason: str) -> None:
        """Permanent-until-replaced governance decision — distinct from the
        health-driven ERROR/'unhealthy' tier: a human or policy is choosing
        to stop using this agent, not the agent failing on its own. Not
        reversible via reactivate() (register a replacement agent instead —
        matches the audit's own "replace/promote" framing)."""
        self.state = AgentState.RETIRED
        self.metadata["retired_reason"] = reason
        self.metadata["retired_at"] = _now().isoformat()

    def reactivate(self) -> None:
        """Undo disable() only. A RETIRED agent stays retired — see
        retire()'s own docstring for why that's deliberate."""
        if self.state == AgentState.DISABLED:
            self.state = AgentState.SLEEP
            self.metadata.pop("disabled_reason", None)
            self.metadata.pop("disabled_at", None)


def _publish_lifecycle_event(agent_name: str, instance: AgentInstance) -> None:
    """AUDIT_Q_BATCH14 §77/§94 gap-closure — persists a disable/retire/
    reactivate transition via the existing agent.health_updated event
    (health_updated()'s payload already carries `state`, which
    reseed_health_from_events previously wrote but never read back). Best
    effort, never raises — an event-publish failure must not affect the
    real in-memory state change the caller already applied."""
    try:
        from app.fleet.fleet_events import health_updated, publish

        publish(
            health_updated(
                agent_name, health=instance.health, state=instance.state.value
            )
        )
    except Exception:
        logger.debug(
            "Could not publish lifecycle event for %s", agent_name, exc_info=True
        )


def _notify_agent_retired(agent_name: str, reason: str) -> None:
    """AUDIT_Q_BATCH16 §89 gap-closure (2026-08-11) — best-effort, never
    raises. Reuses fleet_events.get_main_loop()'s already-captured FastAPI
    main loop (the same cross-thread-safe dispatch FleetBus itself uses)
    instead of re-implementing loop capture — fail_task() is called from
    arbitrary contexts, including asyncio.to_thread worker threads with no
    event loop of their own (base_graph.py's run_agent_graph exception
    handler), so a plain `await` here isn't possible."""
    try:
        import asyncio

        from app.fleet.fleet_events import get_main_loop
        from app.services.alert import send_agent_alert

        coro = send_agent_alert(agent_name, "unhealthy", reason)
        loop = get_main_loop()
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        running.create_task(coro)
    except Exception:
        logger.debug(
            "Could not send agent-retired alert for %s", agent_name, exc_info=True
        )


class AgentRegistry:
    """Thread-safe live registry of agent instances."""

    def __init__(self) -> None:
        self._instances: dict[str, AgentInstance] = {}
        self._lock = threading.RLock()

    def register(self, name: str, **metadata: Any) -> AgentInstance:
        with self._lock:
            if name not in self._instances:
                self._instances[name] = AgentInstance(name=name, metadata=metadata)
            return self._instances[name]

    def get(self, name: str) -> AgentInstance | None:
        with self._lock:
            return self._instances.get(name)

    def deregister(self, name: str) -> AgentInstance | None:
        """Real removal, distinct from disable()/retire() (both of which
        intentionally keep the entry forever for the 86 real agents, and
        both publish a lifecycle event for a human to see — a governance
        signal). A scrapped temporary_agent instance isn't a governance
        event, it's routine cleanup, so this deliberately does NOT call
        _publish_lifecycle_event/_notify_agent_retired. Returns the removed
        instance (or None if it wasn't present — idempotent, safe to call
        twice from a racing TTL-sweep vs. natural-completion path)."""
        with self._lock:
            return self._instances.pop(name, None)

    def available(self) -> list[AgentInstance]:
        with self._lock:
            return [i for i in self._instances.values() if i.is_available]

    def running(self) -> list[AgentInstance]:
        with self._lock:
            return [
                i for i in self._instances.values() if i.state == AgentState.RUNNING
            ]

    def all(self) -> list[AgentInstance]:
        with self._lock:
            return list(self._instances.values())

    def start_task(self, name: str, task_id: str | None = None) -> AgentInstance:
        with self._lock:
            instance = self._instances.setdefault(name, AgentInstance(name=name))
            instance.start(task_id or str(uuid.uuid4()))
            return instance

    def try_start_task(
        self, name: str, task_id: str | None = None
    ) -> AgentInstance | None:
        """Atomic check-and-start: mark `name` RUNNING only if it is STILL
        available, all under the registry lock. Returns None if another caller
        got there first.

        FleetManager.select() (availability check) and start_task() (mark
        running) are two separate steps, so two concurrent dispatchers could both
        pass the check and both be handed the same single-flight agent — observed
        under a thread stress test (1 in 400 rounds of 6 concurrent dispatches).
        """
        with self._lock:
            instance = self._instances.setdefault(name, AgentInstance(name=name))
            if not instance.is_available:
                return None
            instance.start(task_id or str(uuid.uuid4()))
            return instance

    def complete_task(
        self, name: str, confidence: float | None = None
    ) -> AgentInstance | None:
        with self._lock:
            instance = self._instances.get(name)
            if instance:
                instance.complete(confidence=confidence)
            return instance

    def fail_task(self, name: str, reason: str) -> AgentInstance | None:
        with self._lock:
            instance = self._instances.get(name)
            if instance is None:
                return None
            was_unhealthy = instance.health == "unhealthy"
            instance.fail(reason)
            newly_unhealthy = instance.health == "unhealthy" and not was_unhealthy
        if newly_unhealthy:
            # AUDIT_Q_BATCH16 §89 gap-closure (2026-08-11) — "Notify a
            # supervisor" was NO: FleetManager.select() already excludes an
            # unhealthy agent (real, code-enforced), but nothing ever told
            # a human it happened — only an internal metadata field
            # changed. Fired outside the lock (never hold a threading.RLock
            # across a call that may schedule cross-thread work) and
            # best-effort — a notification failure must never affect the
            # real exclusion decision this method's caller depends on.
            _notify_agent_retired(name, reason)
        return instance

    def disable(self, name: str, reason: str) -> AgentInstance | None:
        """AUDIT_Q_BATCH14 §77/§94 gap-closure — real caller: POST
        /api/registry/{name}/lifecycle (app/api/registry.py). Persists via
        the same agent.health_updated event `reseed_health_from_events`
        already reads on startup (payload's `state` field, previously
        written but never re-read) — new AgentState values, not a new
        event type or persistence path."""
        with self._lock:
            instance = self._instances.setdefault(name, AgentInstance(name=name))
            instance.disable(reason)
        _publish_lifecycle_event(name, instance)
        return instance

    def retire(self, name: str, reason: str) -> AgentInstance | None:
        with self._lock:
            instance = self._instances.setdefault(name, AgentInstance(name=name))
            instance.retire(reason)
        _publish_lifecycle_event(name, instance)
        _notify_agent_retired(name, reason)
        return instance

    def reactivate(self, name: str) -> AgentInstance | None:
        with self._lock:
            instance = self._instances.get(name)
            if instance is None:
                return None
            instance.reactivate()
        _publish_lifecycle_event(name, instance)
        return instance

    def recover_task(self, name: str) -> AgentInstance | None:
        """AUDIT_Q_BATCH16 §88 gap-closure (2026-08-11) — recover() existed
        (agent_registry.py, since Phase F2) but had zero real callers
        anywhere in the codebase (confirmed by grepping every call site
        before this change): once an instance degraded/went unhealthy, it
        stayed that way until the whole process restarted, which is a
        different, accidental form of "recovery," not automatic. Real
        caller: base_graph.py's run_agent_graph() finalization, gated on
        final_state["submitted"] — a genuinely successful completion is the
        correct recovery signal, not merely reaching this method (see that
        call site's own comment for why it isn't folded into complete_task()
        itself: complete_task() also runs right after a stall's escalate()
        ->fail_task() within the SAME call, so an unconditional recover()
        there would immediately erase the failure it just recorded)."""
        with self._lock:
            instance = self._instances.get(name)
            if instance and instance.health != "healthy":
                instance.recover()
            return instance

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": i.name,
                    "state": i.state.value,
                    "current_task_id": i.current_task_id,
                    "health": i.health,
                    "is_available": i.is_available,
                    "total_runs": i.total_runs,
                    "error_count": i.error_count,
                    "last_active": i.last_active.isoformat(),
                }
                for i in self._instances.values()
            ]


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_agent_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    return _agent_registry


async def reseed_health_from_events(db: Any) -> int:
    """AUDIT_Q_BATCH16 §89 gap-closure (2026-08-11) — "Replace / permanently
    disable" was NO: FleetManager.select()'s real, code-enforced unhealthy
    exclusion lived only in this in-process AgentRegistry, so a process
    restart silently cleared it — "closer to temporary in-process cooldown
    than a governed lifecycle decision" per the audit's own framing. Now
    that HEALTH_UPDATED events are actually persisted to the real `events`
    table (see fleet_events.py's FLEET_TO_LEGACY gap-closure, same batch),
    this reads the most recently persisted health per agent and re-applies
    "unhealthy" before the fresh process starts dispatching — a genuinely
    persistent retirement, not merely an accidental one-time reset. Called
    once from FastAPI lifespan startup (app/main.py), on the same loop as
    ensure_all_agents_registered(), before any real dispatch can occur.
    Best-effort: never raises, never blocks startup on a query failure —
    an agent whose health can't be determined starts healthy, the existing
    pre-gap-closure behavior, not a new failure mode.
    """
    try:
        from sqlalchemy import select

        from app.db.models import Event

        query = (
            select(Event.emitted_by, Event.payload)
            .where(Event.event_type == "agent.health_updated")
            .order_by(Event.emitted_by, Event.created_at.desc())
            .distinct(Event.emitted_by)
        )
        result = await db.execute(query)
        seeded = 0
        for agent_name, payload in result.all():
            if not agent_name:
                continue
            data = payload or {}
            health = data.get("health")
            # AUDIT_Q_BATCH14 §77/§94 gap-closure (2026-08-12) — the payload's
            # `state` field was already written by every health_updated()
            # call (including disable()/retire() below) but never read back
            # here, so a DISABLED/RETIRED governance decision — unlike
            # "unhealthy" — was silently lost on every restart despite being
            # persisted. Re-apply it the same way "unhealthy" already is.
            state = data.get("state")
            if state == AgentState.RETIRED.value:
                instance = _agent_registry.register(agent_name)
                instance.state = AgentState.RETIRED
                instance.metadata["retired_reason"] = "re-seeded from persisted event"
                seeded += 1
            elif state == AgentState.DISABLED.value:
                instance = _agent_registry.register(agent_name)
                instance.state = AgentState.DISABLED
                instance.metadata["disabled_reason"] = "re-seeded from persisted event"
                seeded += 1
            elif health == "unhealthy":
                instance = _agent_registry.register(agent_name)
                instance.health = "unhealthy"
                instance.error_count = 3
                seeded += 1
        if seeded:
            logger.info(
                "Re-seeded %d agent(s) from persisted health/lifecycle events",
                seeded,
            )
        return seeded
    except Exception:
        logger.warning(
            "Could not re-seed agent health from persisted events (non-fatal)",
            exc_info=True,
        )
        return 0


async def compute_live_success_rate(
    db: Any, agent_type: str, fallback: float
) -> tuple[float, int]:
    """The one real place success_rate is computed from actual AgentRun
    outcomes — AUDIT_Q_BATCH15 §37 gap-closure (2026-08-11) factored this out
    of api/registry.py's get_agent_metrics() (its only prior caller) so
    main.py's new _fleet_success_rate_sync_loop can reuse the exact same
    computation instead of duplicating it. AgentRun.agent_type is a plain
    string column (no FK to the `agents` table — confirmed in
    app/db/models.py), so this reads real run history directly and needs no
    Agent row to exist for agent_type.

    Returns (success_rate, total_runs). fallback is returned unchanged when
    total_runs == 0 — "no runs yet" must never be silently scored as either
    0% or 100%, matching every other real-signal-not-fabricated convention
    in this codebase (e.g. app/memory/store.py's zero-vector skip).
    """
    from sqlalchemy import case, func, select

    from app.db.models import AgentRun

    # Aggregate in SQL (was: load every AgentRun ORM row, output blobs included,
    # for every capability on every sync) and count only FINISHED runs — a run
    # that is still "running" has no outcome yet and must not drag an agent's
    # routing score down while it does its job (an agent busy on a long task
    # looked like it was failing).
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(
                    func.sum(case((AgentRun.status == "completed", 1), else_=0)), 0
                ),
            ).where(AgentRun.agent_type == agent_type, AgentRun.status != "running")
        )
    ).one()
    total, successes = int(row[0]), int(row[1])
    if total == 0:
        return fallback, 0
    return successes / total, total


# ---------------------------------------------------------------------------
# Pre-register the 3 reference agents so they appear in Sleep state at startup
# ---------------------------------------------------------------------------

for _name in ("pm", "bug_fix", "qa"):
    _agent_registry.register(_name)
