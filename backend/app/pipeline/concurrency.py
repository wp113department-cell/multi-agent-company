"""Concurrency caps — asyncio.Semaphore guards for epics, agent runs, subtasks.

Semaphores are module-level singletons (one per process). They are re-created
on Settings change only if the module is reloaded; in production the process
starts fresh so this is fine.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.config import get_settings

logger = logging.getLogger(__name__)

_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


class PrioritySemaphore:
    """Bounded concurrency gate, same acquire/release counting semantics as
    `asyncio.Semaphore` — the only difference is which WAITING caller gets
    woken first when more than one is blocked: highest DevTask.priority
    first, then real FIFO (arrival order) among equal-priority waiters.

    Gap-closure (Batch 2 audit, §2 "Priorities managed"): `DevTask.priority`
    was stored and read back into API responses but never consulted by any
    dispatch/queue code — a plain `asyncio.Semaphore` (used everywhere in
    this module before this fix) only supports FIFO and has no notion of
    priority at all, so there was no place in the concurrency layer that
    COULD have honored it. `agent_run_slot()`/`subtask_slot()` are the one
    real place multiple different DevTasks' dispatched work genuinely
    contends for the same bounded resource (the global agent-run cap and
    the per-epic subtask cap) — this is where priority has an actual,
    observable effect on dispatch order today, unlike `_topological_
    subtask_order()` (manager.py), where every subtask in one call shares
    the SAME task's single priority value and so has nothing to break a
    tie with.

    Implementation mirrors CPython's own `asyncio.locks.Semaphore.acquire()`
    (verified against `inspect.getsource` before writing this) — including
    its exact cancellation-safety contract (a waiter cancelled after
    already being granted a permit hands that permit to the next waiter
    instead of leaking it) — with the FIFO deque swapped for a
    `(priority_rank, sequence)` min-heap.
    """

    def __init__(self, value: int = 1) -> None:
        if value < 0:
            raise ValueError("PrioritySemaphore initial value must be >= 0")
        self._value = value
        self._seq = itertools.count()
        self._waiters: list[tuple[int, int, asyncio.Future[bool]]] = []

    def locked(self) -> bool:
        return self._value == 0 or any(
            not fut.cancelled() for _, _, fut in self._waiters
        )

    async def acquire(self, priority: str = "medium") -> bool:
        if not self.locked():
            self._value -= 1
            return True

        rank = _PRIORITY_RANK.get(priority, _PRIORITY_RANK["medium"])
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        entry = (rank, next(self._seq), fut)
        heapq.heappush(self._waiters, entry)

        try:
            await fut
        except asyncio.CancelledError:
            if not fut.cancelled():
                # Already granted a permit (fut.set_result ran in
                # _wake_up_next) but unwinding anyway — hand it to the next
                # waiter instead of leaking it, exactly like stdlib.
                self._value += 1
                self._wake_up_next()
            raise
        finally:
            self._remove_waiter(entry)

        if self._value > 0:
            self._wake_up_next()
        return True

    def release(self) -> None:
        self._value += 1
        self._wake_up_next()

    def _remove_waiter(self, entry: tuple[int, int, "asyncio.Future[bool]"]) -> None:
        try:
            self._waiters.remove(entry)
        except ValueError:
            return
        heapq.heapify(self._waiters)

    def _wake_up_next(self) -> None:
        """Wake the highest-priority (then earliest-arrived) waiter that isn't done."""
        while self._waiters:
            _, _, fut = self._waiters[0]
            if fut.done():
                heapq.heappop(self._waiters)
                continue
            heapq.heappop(self._waiters)
            self._value -= 1
            fut.set_result(True)
            return


_epic_sem: asyncio.Semaphore | None = None
_agent_run_sem: PrioritySemaphore | None = None
_subtask_sems: dict[str, PrioritySemaphore] = {}


class SlotAcquisitionTimeout(Exception):
    """MASTER_AGENT_v2.md Phase 5.6 — raised when a slot can't be acquired
    within slot_acquisition_timeout_seconds. A loud, specific failure
    instead of a silent hang, for the bounded deadlock risk this project's
    real concurrency model (in-process asyncio.Semaphore, not a distributed
    lock manager) can actually produce: an epic holding a subtask slot while
    waiting on another subtask that can never acquire one because the
    epic's own concurrency cap is exhausted."""

    def __init__(self, slot_kind: str, timeout_seconds: float) -> None:
        self.slot_kind = slot_kind
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Timed out after {timeout_seconds}s waiting for a {slot_kind} slot "
            "— possible deadlock (a slot that can never be freed)"
        )


def _get_epic_sem() -> asyncio.Semaphore:
    global _epic_sem
    if _epic_sem is None:
        _epic_sem = asyncio.Semaphore(get_settings().max_concurrent_epics)
    return _epic_sem


def _get_agent_run_sem() -> PrioritySemaphore:
    global _agent_run_sem
    if _agent_run_sem is None:
        _agent_run_sem = PrioritySemaphore(get_settings().max_concurrent_agent_runs)
    return _agent_run_sem


def _get_subtask_sem(epic_id: str) -> PrioritySemaphore:
    if epic_id not in _subtask_sems:
        _subtask_sems[epic_id] = PrioritySemaphore(
            get_settings().max_concurrent_subtasks_per_epic
        )
    return _subtask_sems[epic_id]


@asynccontextmanager
async def epic_slot() -> AsyncIterator[None]:
    """Acquire the global epic concurrency slot before starting an epic run."""
    sem = _get_epic_sem()
    async with sem:
        logger.debug(
            "Epic slot acquired"
        )  # _value is internal; omit to keep mypy clean
        yield


@asynccontextmanager
async def agent_run_slot(priority: str = "medium") -> AsyncIterator[None]:
    """Acquire a global agent-run slot before calling run_agent(). Bounded
    wait (Phase 5.6) — raises SlotAcquisitionTimeout instead of hanging
    forever if no slot frees up in time.

    priority (Batch 2 audit gap-closure): the dispatching DevTask's real
    `priority` column ("high"/"medium"/"low") — when multiple different
    tasks' agents are simultaneously waiting for this global cap, the
    higher-priority one is granted the slot first. Defaults to "medium" so
    any caller that doesn't pass it keeps today's behavior unchanged when
    priorities are uniform.
    """
    sem = _get_agent_run_sem()
    timeout = get_settings().slot_acquisition_timeout_seconds
    try:
        await asyncio.wait_for(sem.acquire(priority=priority), timeout=timeout)
    except asyncio.TimeoutError:
        raise SlotAcquisitionTimeout("agent_run", timeout) from None
    try:
        yield
    finally:
        sem.release()


@asynccontextmanager
async def subtask_slot(
    epic_id: str, priority: str = "medium"
) -> AsyncIterator[None]:
    """Acquire a per-epic subtask slot before dispatching a subtask. Bounded
    wait (Phase 5.6) — raises SlotAcquisitionTimeout instead of hanging
    forever if no slot frees up in time.

    priority: see `agent_run_slot`'s docstring — same semantics, scoped to
    this epic's own subtask cap instead of the global agent-run cap.
    """
    sem = _get_subtask_sem(epic_id)
    timeout = get_settings().slot_acquisition_timeout_seconds
    try:
        await asyncio.wait_for(sem.acquire(priority=priority), timeout=timeout)
    except asyncio.TimeoutError:
        raise SlotAcquisitionTimeout("subtask", timeout) from None
    try:
        yield
    finally:
        sem.release()


def reset_for_testing(
    max_epics: int = 10,
    max_agent_runs: int = 20,
    max_subtasks_per_epic: int = 5,
) -> None:
    """Replace module-level semaphores with new ones — test helper only."""
    global _epic_sem, _agent_run_sem, _subtask_sems
    _epic_sem = asyncio.Semaphore(max_epics)
    _agent_run_sem = PrioritySemaphore(max_agent_runs)
    _subtask_sems = {}
