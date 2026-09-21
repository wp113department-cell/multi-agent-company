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
        "entry_id",
        "trace_id",
        "timestamp",
        "action_type",
        "agent_name",
        "task_id",
        "description",
        "details",
        "outcome",
        "requires_human_approval",
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
        entry_id: str | None = None,
        timestamp: datetime | str | None = None,
    ) -> None:
        # entry_id/timestamp are normally auto-generated (real append()
        # calls never pass them) — the two optional overrides exist only
        # for AuditLog._row_to_entry (AUDIT_Q_BATCH11 §96), which
        # reconstructs an AuditEntry from a DB row and must preserve that
        # row's original identity/time, not mint a fresh one.
        self.entry_id = entry_id or str(uuid.uuid4())
        self.trace_id = trace_id or ""
        self.timestamp = timestamp or _now()
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
    # Async query (read from the durable DB table) — AUDIT_Q_BATCH11 §96
    # ------------------------------------------------------------------
    #
    # recent()/by_trace()/by_task()/approvals() above are real and stay
    # exactly as they were (every existing sync caller/test keeps working
    # unchanged) — but they only ever read the in-process ring buffer:
    # capped at `capacity` (2000) entries and reset to empty on every
    # process restart, even though _write_to_db() has been durably
    # persisting every entry to Postgres the entire time. These async
    # counterparts read the actual source of truth. Each falls back to the
    # ring-buffer version (best-effort, matching append()'s own "audit must
    # not block or fail the caller" philosophy) if the DB is unreachable —
    # a broken audit *query* path should degrade, not raise, for the exact
    # same reason a broken audit *write* path already doesn't raise.

    @staticmethod
    def _row_to_entry(row: Any) -> AuditEntry:
        details = row["details"]
        if isinstance(details, str):  # defensive: some drivers may not auto-decode
            try:
                details = json.loads(details)
            except (TypeError, ValueError):
                details = {}
        return AuditEntry(
            entry_id=row["entry_id"],
            trace_id=row["trace_id"] or None,
            timestamp=row["timestamp"],
            action_type=row["action_type"],
            agent_name=row["agent_name"],
            task_id=row["task_id"],
            description=row["description"],
            details=details or {},
            outcome=row["outcome"],
            requires_human_approval=row["requires_human_approval"],
            approved_by=row["approved_by"],
        )

    async def _query_db(
        self,
        *,
        trace_id: str | None = None,
        task_id: str | None = None,
        requires_human_approval: bool | None = None,
        before: datetime | None = None,
        limit: int,
    ) -> list[AuditEntry]:
        from sqlalchemy import text

        from app.db.session import get_session_factory

        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if trace_id is not None:
            conditions.append("trace_id = :trace_id")
            params["trace_id"] = trace_id
        if task_id is not None:
            conditions.append("task_id = :task_id")
            params["task_id"] = task_id
        if requires_human_approval is not None:
            conditions.append("requires_human_approval = :requires_human_approval")
            params["requires_human_approval"] = requires_human_approval
        if before is not None:
            # AUDIT_Q_BATCH14 §48 gap-closure — real cursor pagination over
            # the already-unbounded DB-backed query (the 2000-entry cap only
            # ever applied to the in-memory ring-buffer fallback used when
            # the DB is unreachable). Strict `<` so the cursor's own entry
            # isn't repeated on the next page.
            conditions.append("timestamp < :before")
            params["before"] = before
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT entry_id, trace_id, timestamp, action_type, agent_name, "
                    "task_id, description, details, outcome, "
                    "requires_human_approval, approved_by "
                    f"FROM audit_log {where_clause} "
                    "ORDER BY timestamp DESC LIMIT :limit"
                ),
                params,
            )
            rows = result.mappings().all()
        return [self._row_to_entry(row) for row in rows]

    async def recent_async(
        self, n: int = 50, *, before: datetime | None = None
    ) -> list[AuditEntry]:
        """DB-backed, authoritative version of recent() — survives restarts
        and isn't capped at the ring buffer's 2000 entries. `before` (new,
        optional) enables real cursor pagination past a single page."""
        try:
            return await self._query_db(limit=n, before=before)
        except Exception:
            logger.warning(
                "AuditLog.recent_async DB query failed — falling back to the "
                "in-process ring buffer",
                exc_info=True,
            )
            return self.recent(n)

    async def by_trace_async(
        self, trace_id: str, *, limit: int = 500, before: datetime | None = None
    ) -> list[AuditEntry]:
        """DB-backed, authoritative version of by_trace()."""
        try:
            return await self._query_db(trace_id=trace_id, limit=limit, before=before)
        except Exception:
            logger.warning(
                "AuditLog.by_trace_async DB query failed — falling back to "
                "the in-process ring buffer",
                exc_info=True,
            )
            return self.by_trace(trace_id)

    async def by_task_async(
        self, task_id: str, *, limit: int = 500, before: datetime | None = None
    ) -> list[AuditEntry]:
        """DB-backed, authoritative version of by_task()."""
        try:
            return await self._query_db(task_id=task_id, limit=limit, before=before)
        except Exception:
            logger.warning(
                "AuditLog.by_task_async DB query failed — falling back to "
                "the in-process ring buffer",
                exc_info=True,
            )
            return self.by_task(task_id)

    async def by_actor_async(self, actor: str, *, limit: int = 500) -> list[AuditEntry]:
        """DB-backed: every entry where `actor` is either the acting agent
        (agent_name) or the human who made an approval decision
        (approved_by). Used by app/api/privacy.py's GDPR/CCPA data-export
        endpoint (AUDIT_Q_BATCH11 §96 "Compliance readiness") to answer
        "what audit history is attributable to this identity" — a genuine
        OR across two columns, so it doesn't fit _query_db's AND-only
        condition builder."""
        try:
            from sqlalchemy import text

            from app.db.session import get_session_factory

            async with get_session_factory()() as session:
                result = await session.execute(
                    text(
                        "SELECT entry_id, trace_id, timestamp, action_type, agent_name, "
                        "task_id, description, details, outcome, "
                        "requires_human_approval, approved_by "
                        "FROM audit_log WHERE agent_name = :actor OR approved_by = :actor "
                        "ORDER BY timestamp DESC LIMIT :limit"
                    ),
                    {"actor": actor, "limit": limit},
                )
                rows = result.mappings().all()
            return [self._row_to_entry(row) for row in rows]
        except Exception:
            logger.warning(
                "AuditLog.by_actor_async DB query failed — falling back to "
                "the in-process ring buffer",
                exc_info=True,
            )
            with self._lock:
                return [
                    e
                    for e in self._ring
                    if e.agent_name == actor or e.approved_by == actor
                ][-limit:]

    async def approvals_async(
        self, *, limit: int = 100, before: datetime | None = None
    ) -> list[AuditEntry]:
        """DB-backed, authoritative version of approvals()."""
        try:
            return await self._query_db(
                requires_human_approval=True, limit=limit, before=before
            )
        except Exception:
            logger.warning(
                "AuditLog.approvals_async DB query failed — falling back to "
                "the in-process ring buffer",
                exc_info=True,
            )
            return self.approvals(limit=limit)

    # ------------------------------------------------------------------
    # Chain integrity verification — AUDIT_Q_BATCH18 Bonus-table row 7
    # gap-closure (2026-08-12)
    # ------------------------------------------------------------------
    #
    # Migration 036 (AUDIT_Q_BATCH11 §96) already gave audit_log a real,
    # DB-enforced hash chain (BEFORE INSERT trigger computing
    # entry_hash = sha256(prev_hash || every other column)) plus triggers
    # rejecting UPDATE/DELETE outright — genuinely stronger tamper
    # resistance than an application-level check could provide on its own.
    # But nothing anywhere ever READ entry_hash/prev_hash back to confirm
    # the chain is actually intact (grepped: zero references outside the
    # migration itself before this) — a row could still be altered by
    # anything that bypasses the trigger layer (a direct write under
    # `SET LOCAL audit_log.allow_mutation = true`, a restored backup with a
    # gap, manual DB surgery by a superuser) and nothing would ever notice.
    # This is that missing read-back: it recomputes the exact same
    # sha256(prev_hash || ...) expression the trigger uses, entirely in
    # SQL (never re-serializing `details` in Python — Postgres's own
    # `jsonb::text` cast is what the trigger hashed, and re-implementing
    # that byte-for-byte in Python would risk spurious mismatches from
    # whitespace/ordering differences, not real tampering), so a mismatch
    # here is never a false positive from a serialization difference.

    async def verify_chain(
        self, *, since_seq: int = 1, max_rows: int = 200_000
    ) -> dict[str, Any]:
        """Recomputes and checks the hash chain for seq >= since_seq
        (default: the whole table, from seq=1), bounded by max_rows as a
        safety cap. `since_seq` enables a real incremental/windowed check
        (e.g. "verify everything written since the last verification run")
        without the classic hash-chain-window bug: the row immediately
        BEFORE since_seq is fetched as an anchor so the first row in the
        window is still checked against its true expected prev_hash rather
        than an assumed-empty one — since_seq=1 naturally degrades to the
        same '' bootstrap value migration 036's own trigger uses for the
        very first row ever, so the two code paths are one query, not two.

        Returns {checked, intact, first_break, breaks} — breaks is capped
        at 50 entries so a badly-corrupted table doesn't return an
        unbounded response.

        Never raises: an unreachable DB or a table that predates migration
        036 (no entry_hash column) both return intact=None (distinct from
        True/False) with an `error` key — "could not verify" must never be
        reported as "verified intact", the same false-success class of bug
        this whole audit exists to catch.
        """
        try:
            from sqlalchemy import text

            from app.db.session import get_session_factory

            async with get_session_factory()() as session:
                # The chain is verified as a LINKED LIST (each row's prev_hash is the
                # entry_hash of exactly one existing row; one root), not by walking seq
                # order. seq is assigned before the trigger takes its advisory lock, so two
                # concurrent inserts can commit in the opposite order to their seq values:
                # the chain is intact in commit order but the old LAG-over-seq check
                # reported those valid rows as breaks (14 false breaks in a 545-row table),
                # which makes a real break impossible to tell from noise.
                # rows before migration 049 may contain forks from the concurrent-insert race
                # (and, in test databases, deleted parents): their CONTENT hashes are still
                # verified, their LINKS are only checked from that migration's boundary on
                boundary_row = (
                    await session.execute(
                        text(
                            "SELECT value FROM system_settings "
                            "WHERE key = 'audit_chain_fork_free_since_seq'"
                        )
                    )
                ).first()
                fork_free_from = int(boundary_row[0]) if boundary_row else 1
                result = await session.execute(
                    text(
                        "WITH windowed AS ("
                        "  SELECT seq, entry_id, timestamp, prev_hash, entry_hash, "
                        "         action_type, agent_name, task_id, description, "
                        "         details, outcome, requires_human_approval, approved_by "
                        "  FROM audit_log WHERE seq >= :since_seq "
                        "  ORDER BY seq LIMIT :max_rows"
                        "), children AS ("
                        "  SELECT prev_hash, count(*) AS n FROM audit_log GROUP BY prev_hash"
                        "), roots AS ("
                        "  SELECT count(*) AS n FROM audit_log WHERE prev_hash = ''"
                        ") "
                        "SELECT w.seq, w.entry_id, w.timestamp, "
                        "w.entry_hash = encode(digest("
                        "  w.prev_hash || w.entry_id || w.timestamp || w.action_type || "
                        "  w.agent_name || COALESCE(w.task_id, '') || w.description || "
                        "  COALESCE(w.details::text, '') || w.outcome || "
                        "  w.requires_human_approval::text || COALESCE(w.approved_by, ''), "
                        "  'sha256'), 'hex') AS content_hash_valid, "
                        "(w.seq < :fork_free_from OR ("
                        "  (CASE WHEN w.prev_hash = '' THEN r.n = 1 "
                        "        ELSE p.entry_hash IS NOT NULL END) "
                        "  AND COALESCE(c.n, 0) <= 1)) "
                        "AS chain_link_valid "
                        "FROM windowed w "
                        "CROSS JOIN roots r "
                        "LEFT JOIN audit_log p ON p.entry_hash = w.prev_hash "
                        "LEFT JOIN children c ON c.prev_hash = w.entry_hash "
                        "ORDER BY w.seq"
                    ),
                    {
                        "since_seq": since_seq,
                        "max_rows": max_rows,
                        "fork_free_from": fork_free_from,
                    },
                )
                rows = result.mappings().all()
        except Exception as exc:
            logger.warning("AuditLog.verify_chain could not query DB: %s", exc)
            return {
                "checked": 0,
                "intact": None,
                "breaks": [],
                "error": str(exc),
            }

        breaks = [
            {
                "seq": r["seq"],
                "entry_id": r["entry_id"],
                "timestamp": r["timestamp"],
                "content_hash_valid": r["content_hash_valid"],
                "chain_link_valid": r["chain_link_valid"],
            }
            for r in rows
            if not r["content_hash_valid"] or not r["chain_link_valid"]
        ]
        return {
            "checked": len(rows),
            "intact": not breaks,
            "first_break": breaks[0] if breaks else None,
            "breaks": breaks[:50],
        }

    # ------------------------------------------------------------------
    # Async persistence (fire-and-forget; no DB required)
    # ------------------------------------------------------------------

    def _persist_async(self, entry: AuditEntry) -> None:
        """Schedule the DB write on the server's event loop.

        Agent tool execution — and therefore every policy denial, guardrail block and other
        security-relevant entry — runs in a worker thread (asyncio.to_thread), where
        asyncio.get_event_loop() raises RuntimeError. The old code swallowed that and the entry
        lived only in the bounded in-memory ring buffer: proven with a real DB, an audit()
        from a worker thread never reached the audit_log table. Same cross-thread dispatch the
        lesson store and agent registry use."""
        try:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not None:
                running.create_task(self._write_to_db(entry))
                return
            from app.fleet.fleet_events import get_main_loop

            main = get_main_loop()
            if main is not None and main.is_running():
                asyncio.run_coroutine_threadsafe(self._write_to_db(entry), main)
        except Exception:
            logger.warning("AuditLog could not schedule the DB write", exc_info=True)

    async def _write_to_db(self, entry: AuditEntry) -> None:
        try:
            from app.db.session import get_session_factory
            from sqlalchemy import text

            async with get_session_factory()() as session:
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
            # was `pass`: a failing audit write was invisible
            logger.warning(
                "AuditLog DB write failed for %s", entry.entry_id, exc_info=True
            )


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
