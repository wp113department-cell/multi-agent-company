"""Batch 2 audit gap-closure (§2 "Priorities managed") — DevTask.priority
was stored and read back into API responses but never consulted by any
dispatch/queue code (a plain asyncio.Semaphore, used everywhere in
app/pipeline/concurrency.py before this fix, only supports FIFO). These
tests prove PrioritySemaphore actually changes wake-up order by priority,
preserves the bounded-concurrency invariant a plain Semaphore gives, and
never leaks a permit on cancellation (the same contract
asyncio.locks.Semaphore.acquire() gives, verified against
inspect.getsource(asyncio.locks.Semaphore) before implementing).
"""

from __future__ import annotations

import asyncio

import pytest

from app.pipeline.concurrency import PrioritySemaphore


@pytest.mark.asyncio
async def test_higher_priority_waiter_is_woken_before_lower_priority() -> None:
    """3 low-priority callers grab the only slot's queue first; a 'high'
    caller arriving after them must still be granted the slot before any of
    the earlier 'low' waiters — proves priority beats arrival order."""
    sem = PrioritySemaphore(1)
    await sem.acquire()  # hold the only slot

    order: list[str] = []

    async def waiter(name: str, priority: str) -> None:
        await sem.acquire(priority=priority)
        order.append(name)
        sem.release()

    tasks = [
        asyncio.create_task(waiter("low-1", "low")),
        asyncio.create_task(waiter("low-2", "low")),
        asyncio.create_task(waiter("low-3", "low")),
    ]
    await asyncio.sleep(0.01)  # let all 3 register as waiters, in that order
    high_task = asyncio.create_task(waiter("high-1", "high"))
    await asyncio.sleep(0.01)

    sem.release()  # free the slot held at the top — first waiter should be high-1
    await asyncio.gather(high_task, *tasks)

    assert order[0] == "high-1"
    assert order[1:] == ["low-1", "low-2", "low-3"]


@pytest.mark.asyncio
async def test_equal_priority_preserves_fifo_order() -> None:
    sem = PrioritySemaphore(1)
    await sem.acquire()

    order: list[int] = []

    async def waiter(n: int) -> None:
        await sem.acquire(priority="medium")
        order.append(n)
        sem.release()

    tasks = []
    for i in range(4):
        tasks.append(asyncio.create_task(waiter(i)))
        await asyncio.sleep(0.005)

    sem.release()
    await asyncio.gather(*tasks)

    assert order == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_never_exceeds_bound_under_mixed_priority_contention() -> None:
    sem = PrioritySemaphore(2)
    active: list[int] = []
    peak: list[int] = []

    async def run(n: int, priority: str) -> None:
        await sem.acquire(priority=priority)
        try:
            active.append(n)
            peak.append(len(active))
            await asyncio.sleep(0.01)
        finally:
            active.remove(n)
            sem.release()

    priorities = ["low", "high", "medium", "low", "high", "medium"]
    await asyncio.gather(*[run(i, p) for i, p in enumerate(priorities)])

    assert max(peak) <= 2


@pytest.mark.asyncio
async def test_unknown_priority_defaults_to_medium_rank() -> None:
    sem = PrioritySemaphore(1)
    await sem.acquire()

    order: list[str] = []

    async def waiter(name: str, priority: str) -> None:
        await sem.acquire(priority=priority)
        order.append(name)
        sem.release()

    med_task = asyncio.create_task(waiter("medium-explicit", "medium"))
    await asyncio.sleep(0.005)
    unknown_task = asyncio.create_task(waiter("unknown-tier", "not-a-real-priority"))
    await asyncio.sleep(0.005)

    sem.release()
    await asyncio.gather(med_task, unknown_task)

    # Both rank as "medium" -> arrival order (FIFO) decides, not an error.
    assert order == ["medium-explicit", "unknown-tier"]


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leak_a_permit() -> None:
    """A waiter cancelled while blocked must not silently reduce the
    effective concurrency cap forever (a leaked, never-released permit) —
    mirrors asyncio.Semaphore's own cancellation-safety contract."""
    sem = PrioritySemaphore(1)
    await sem.acquire()  # hold the only slot

    waiter_task = asyncio.create_task(sem.acquire(priority="medium"))
    await asyncio.sleep(0.01)
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    sem.release()  # release the original holder's slot

    # A fresh acquire must succeed promptly — if the cancelled waiter's
    # eventual grant had leaked, this would hang until the test times out.
    await asyncio.wait_for(sem.acquire(priority="medium"), timeout=1.0)


@pytest.mark.asyncio
async def test_immediate_acquire_when_slot_free_no_wait() -> None:
    sem = PrioritySemaphore(2)
    await sem.acquire(priority="low")
    await sem.acquire(priority="high")
    assert sem.locked()
    sem.release()
    sem.release()
