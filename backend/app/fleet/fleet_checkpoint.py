"""Fleet OS checkpoint — save and restore AgentRunState snapshots.

Pattern from: roo-code src/core/checkpoints/ + langgraph libs/checkpoint/

Provides a save → restore → rollback cycle so any agent run can be
rewound to a previous known-good state before a risky operation.

Usage:
    from app.fleet.fleet_checkpoint import save_checkpoint, rollback_to

    # Before a risky tool call:
    ckpt_id = save_checkpoint(state, agent_name="coder", task_id=task_id, label="before_migration")

    # If the tool fails, restore:
    restored = rollback_to(ckpt_id)
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


# Serializable snapshot of AgentRunState (plain dict, deep-copied on save and restore)
AgentStateSnapshot = dict[str, Any]


@dataclass
class AgentCheckpoint:
    """One saved snapshot of an agent's runtime state."""

    checkpoint_id: str
    agent_name: str
    task_id: str
    created_at: datetime
    state_snapshot: AgentStateSnapshot
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "created_at": self.created_at.isoformat(),
            "label": self.label,
            "turns_saved": self.state_snapshot.get("turns", 0),
            "metadata": self.metadata,
        }


class CheckpointStore:
    """Thread-safe in-process ring buffer of AgentCheckpoints.

    Capacity defaults to 500 checkpoints. When full, the oldest is evicted.
    Deep-copy on both save and restore ensures stored snapshots are immutable.
    """

    def __init__(self, capacity: int = 500) -> None:
        self._capacity = capacity
        self._store: dict[str, AgentCheckpoint] = {}
        self._order: list[str] = []  # insertion order for FIFO eviction
        self._lock = Lock()
        self._total_saved = 0

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save(
        self,
        state: AgentStateSnapshot,
        agent_name: str,
        task_id: str = "",
        label: str = "",
        metadata: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> str:
        """Deep-copy state and return a new checkpoint_id."""
        checkpoint_id = f"ckpt-{uuid.uuid4().hex[:12]}"
        merged_metadata = dict(metadata or {})
        if trace_id:
            merged_metadata["trace_id"] = trace_id
        cp = AgentCheckpoint(
            checkpoint_id=checkpoint_id,
            agent_name=agent_name,
            task_id=task_id,
            created_at=datetime.now(timezone.utc),
            state_snapshot=copy.deepcopy(state),
            label=label,
            metadata=merged_metadata,
        )
        with self._lock:
            if len(self._store) >= self._capacity:
                oldest = self._order.pop(0)
                del self._store[oldest]
            self._store[checkpoint_id] = cp
            self._order.append(checkpoint_id)
            self._total_saved += 1
        return checkpoint_id

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def restore(self, checkpoint_id: str) -> AgentStateSnapshot | None:
        """Return a deep-copy of the saved state, or None if not found."""
        with self._lock:
            cp = self._store.get(checkpoint_id)
        if cp is None:
            return None
        return copy.deepcopy(cp.state_snapshot)

    def rollback(self, checkpoint_id: str) -> AgentStateSnapshot:
        """Return a deep-copy of the saved state. Raises KeyError if not found."""
        state = self.restore(checkpoint_id)
        if state is None:
            raise KeyError(
                f"Checkpoint {checkpoint_id!r} not found — cannot rollback. "
                "The checkpoint may have been evicted (capacity exceeded) or never saved."
            )
        return state

    def get(self, checkpoint_id: str) -> AgentCheckpoint | None:
        """Return the AgentCheckpoint metadata (not a copy of state)."""
        with self._lock:
            return self._store.get(checkpoint_id)

    def list_checkpoints(
        self,
        agent_name: str | None = None,
        task_id: str | None = None,
    ) -> list[AgentCheckpoint]:
        """List checkpoints, optionally filtered by agent_name and/or task_id."""
        with self._lock:
            cps = list(self._store.values())
        if agent_name is not None:
            cps = [c for c in cps if c.agent_name == agent_name]
        if task_id is not None:
            cps = [c for c in cps if c.task_id == task_id]
        return cps

    def latest_for(self, agent_name: str, task_id: str = "") -> AgentCheckpoint | None:
        """Return the most recently saved checkpoint for this agent/task."""
        cps = self.list_checkpoints(agent_name=agent_name, task_id=task_id or None)
        if not cps:
            return None
        return max(cps, key=lambda c: c.created_at)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def total_saved(self) -> int:
        """Total checkpoints ever saved (even if evicted)."""
        return self._total_saved

    @property
    def current_size(self) -> int:
        """Number of checkpoints currently in the store."""
        with self._lock:
            return len(self._store)


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------

_checkpoint_store: CheckpointStore | None = None
_store_lock = Lock()


def get_checkpoint_store() -> CheckpointStore:
    """Return the process-wide CheckpointStore singleton."""
    global _checkpoint_store
    if _checkpoint_store is None:
        with _store_lock:
            if _checkpoint_store is None:
                _checkpoint_store = CheckpointStore()
    return _checkpoint_store


# ---------------------------------------------------------------------------
# Module-level convenience functions (operate on singleton)
# ---------------------------------------------------------------------------

def save_checkpoint(
    state: AgentStateSnapshot,
    agent_name: str,
    task_id: str = "",
    label: str = "",
    metadata: dict[str, Any] | None = None,
    trace_id: str = "",
) -> str:
    """Save a checkpoint and return its ID. Uses the process-wide store."""
    return get_checkpoint_store().save(
        state, agent_name=agent_name, task_id=task_id, label=label,
        metadata=metadata, trace_id=trace_id,
    )


def restore_checkpoint(checkpoint_id: str) -> AgentStateSnapshot | None:
    """Restore a snapshot by ID. Returns None if not found."""
    return get_checkpoint_store().restore(checkpoint_id)


def rollback_to(checkpoint_id: str) -> AgentStateSnapshot:
    """Restore a snapshot by ID. Raises KeyError if not found."""
    return get_checkpoint_store().rollback(checkpoint_id)
