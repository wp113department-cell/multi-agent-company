"""Concurrency caps — asyncio.Semaphore guards for epics, agent runs, subtasks.

Semaphores are module-level singletons (one per process). They are re-created
on Settings change only if the module is reloaded; in production the process
starts fresh so this is fine.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.config import get_settings

logger = logging.getLogger(__name__)

_epic_sem: asyncio.Semaphore | None = None
_agent_run_sem: asyncio.Semaphore | None = None
_subtask_sems: dict[str, asyncio.Semaphore] = {}


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


def _get_agent_run_sem() -> asyncio.Semaphore:
    global _agent_run_sem
    if _agent_run_sem is None:
        _agent_run_sem = asyncio.Semaphore(get_settings().max_concurrent_agent_runs)
    return _agent_run_sem


def _get_subtask_sem(epic_id: str) -> asyncio.Semaphore:
    if epic_id not in _subtask_sems:
        _subtask_sems[epic_id] = asyncio.Semaphore(
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
async def agent_run_slot() -> AsyncIterator[None]:
    """Acquire a global agent-run slot before calling run_agent(). Bounded
    wait (Phase 5.6) — raises SlotAcquisitionTimeout instead of hanging
    forever if no slot frees up in time."""
    sem = _get_agent_run_sem()
    timeout = get_settings().slot_acquisition_timeout_seconds
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        raise SlotAcquisitionTimeout("agent_run", timeout) from None
    try:
        yield
    finally:
        sem.release()


@asynccontextmanager
async def subtask_slot(epic_id: str) -> AsyncIterator[None]:
    """Acquire a per-epic subtask slot before dispatching a subtask. Bounded
    wait (Phase 5.6) — raises SlotAcquisitionTimeout instead of hanging
    forever if no slot frees up in time."""
    sem = _get_subtask_sem(epic_id)
    timeout = get_settings().slot_acquisition_timeout_seconds
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
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
    _agent_run_sem = asyncio.Semaphore(max_agent_runs)
    _subtask_sems = {}
