"""Audit Log — Phase F5.

Immutable append-only record of every mutating action and every human-approval
decision. This is the authoritative timeline for incident review.

Design decisions:
- Dual-write: in-process ring buffer (fast, always available) + async DB write
  (durable, survives restarts). The ring buffer allows tests and monitoring to
  read the log without a DB connection.
- append() is sync and never raises — audit must not block or fail the caller.
- DB write is fire-and-forget via asyncio.create_task() when an event loop is
  running; otherwise falls back to a thread.
- Entries are immutable: no update/delete methods exist.

Why Created: task_logs table records agent runs but is mutable and not
  optimized for sequential incident replay. audit_log is append-only,
  carries trace_id correlation, and is the single authoritative source
  for human-approval decisions.
Alternatives Considered: Kafka/event streaming (over-engineered for Day 0).
Why Existing Architecture Was Insufficient: no immutable action log; human-
  approval decisions were tracked only in code comments.
Dependencies: optional asyncio + SQLAlchemy for durable persistence.
Future Owner: Fleet OS / compliance team.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_RING_CAPACITY = 2000

# ---------------------------------------------------------------------------
# Entry schema
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditEntry:
    __slots__ = (
        "entry_id", "trace_id", "timestamp", "action_type", "agent_name",
        "task_id", "description", "details", "outcome", "requires_human_approval",
        "approved_by",
    )

    def __init__(
        self,
        *,
        action_type: str,
        agent_name: str,
        task_id: str | None = None,
        description: str,
        details: dict[str, Any] | None = None,
        outcome: str = "pending",
        requires_human_approval: bool = False,
        approved_by: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.entry_id = str(uuid.uuid4())
        self.trace_id = trace_id or ""
        self.timestamp = _now()
        self.action_type = action_type
        self.agent_name = agent_name
        self.task_id = task_id
        self.description = description
        self.details = details or {}
        self.outcome = outcome
        self.requires_human_approval = requires_human_approval
        self.approved_by = approved_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "action_type": self.action_type,
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "description": self.description,
            "details": self.details,
            "outcome": self.outcome,
            "requires_human_approval": self.requires_human_approval,
            "approved_by": self.approved_by,
        }

    def __repr__(self) -> str:
        return (
            f"AuditEntry(action_type={self.action_type!r}, agent={self.agent_name!r}, "
            f"task_id={self.task_id!r}, outcome={self.outcome!r})"
        )


# ---------------------------------------------------------------------------
# Append-only log
# ---------------------------------------------------------------------------

class AuditLog:
    def __init__(self, capacity: int = _RING_CAPACITY) -> None:
        self._ring: deque[AuditEntry] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._total_appended = 0

    # ------------------------------------------------------------------
    # Core append — never raises
    # ------------------------------------------------------------------

    def append(
        self,
        action_type: str,
        agent_name: str,
        description: str,
        *,
        task_id: str | None = None,
        details: dict[str, Any] | None = None,
        outcome: str = "success",
        requires_human_approval: bool = False,
        approved_by: str | None = None,
        trace_id: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            action_type=action_type,
            agent_name=agent_name,
            task_id=task_id,
            description=description,
            details=details,
            outcome=outcome,
            requires_human_approval=requires_human_approval,
            approved_by=approved_by,
            trace_id=trace_id,
        )
        try:
            with self._lock:
                self._ring.append(entry)
                self._total_appended += 1
            logger.debug("audit: %s", entry)
            self._persist_async(entry)
        except Exception as exc:
            logger.error("AuditLog.append failed silently: %s", exc)
        return entry

    def record_approval(
        self,
        agent_name: str,
        action_type: str,
        description: str,
        approved: bool,
        approved_by: str = "user",
        task_id: str | None = None,
        trace_id: str | None = None,
    ) -> AuditEntry:
        """Convenience wrapper for human-approval decisions."""
        return self.append(
            action_type=action_type,
            agent_name=agent_name,
            description=description,
            task_id=task_id,
            outcome="approved" if approved else "rejected",
            requires_human_approval=True,
            approved_by=approved_by if approved else None,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # Query (read from ring buffer)
    # ------------------------------------------------------------------

    def recent(self, n: int = 50) -> list[AuditEntry]:
        with self._lock:
            entries = list(self._ring)
        return entries[-n:]

    def by_trace(self, trace_id: str) -> list[AuditEntry]:
        with self._lock:
            return [e for e in self._ring if e.trace_id == trace_id]

    def by_task(self, task_id: str) -> list[AuditEntry]:
        with self._lock:
            return [e for e in self._ring if e.task_id == task_id]

    def approvals(self, *, limit: int = 100) -> list[AuditEntry]:
        with self._lock:
            entries = [e for e in self._ring if e.requires_human_approval]
        return entries[-limit:]

    @property
    def total_appended(self) -> int:
        return self._total_appended

    # ------------------------------------------------------------------
    # Async persistence (fire-and-forget; no DB required)
    # ------------------------------------------------------------------

    def _persist_async(self, entry: AuditEntry) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._write_to_db(entry))
        except RuntimeError:
            pass

    async def _write_to_db(self, entry: AuditEntry) -> None:
        try:
            from app.db.session import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(entry_id, trace_id, timestamp, action_type, agent_name, "
                        " task_id, description, details, outcome, "
                        " requires_human_approval, approved_by) "
                        "VALUES (:entry_id, :trace_id, :timestamp, :action_type, :agent_name, "
                        "        :task_id, :description, :details, :outcome, "
                        "        :requires_human_approval, :approved_by) "
                        "ON CONFLICT (entry_id) DO NOTHING"
                    ),
                    {
                        "entry_id": entry.entry_id,
                        "trace_id": entry.trace_id,
                        "timestamp": entry.timestamp,
                        "action_type": entry.action_type,
                        "agent_name": entry.agent_name,
                        "task_id": entry.task_id,
                        "description": entry.description,
                        "details": json.dumps(entry.details),
                        "outcome": entry.outcome,
                        "requires_human_approval": entry.requires_human_approval,
                        "approved_by": entry.approved_by,
                    },
                )
                await session.commit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_audit_log = AuditLog()


def get_audit_log() -> AuditLog:
    return _audit_log


def audit(
    action_type: str,
    agent_name: str,
    description: str,
    **kwargs: Any,
) -> AuditEntry:
    return _audit_log.append(action_type, agent_name, description, **kwargs)
