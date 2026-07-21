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

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AgentState(str, Enum):
    IDLE = "idle"
    SLEEP = "sleep"
    RUNNING = "running"
    ERROR = "error"


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

    def complete(self) -> None:
        self.state = AgentState.SLEEP
        self.current_task_id = None
        self.last_active = _now()

    def fail(self, reason: str) -> None:
        self.state = AgentState.ERROR
        self.current_task_id = None
        self.last_active = _now()
        self.error_count += 1
        self.metadata["last_error"] = reason
        if self.error_count >= 3:
            self.health = "unhealthy"

    def sleep(self) -> None:
        self.state = AgentState.SLEEP
        self.current_task_id = None

    def recover(self) -> None:
        self.state = AgentState.SLEEP
        self.error_count = 0
        self.health = "healthy"


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

    def complete_task(self, name: str) -> AgentInstance | None:
        with self._lock:
            instance = self._instances.get(name)
            if instance:
                instance.complete()
            return instance

    def fail_task(self, name: str, reason: str) -> AgentInstance | None:
        with self._lock:
            instance = self._instances.get(name)
            if instance:
                instance.fail(reason)
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


# ---------------------------------------------------------------------------
# Pre-register the 3 reference agents so they appear in Sleep state at startup
# ---------------------------------------------------------------------------

for _name in ("pm", "bug_fix", "qa"):
    _agent_registry.register(_name)
