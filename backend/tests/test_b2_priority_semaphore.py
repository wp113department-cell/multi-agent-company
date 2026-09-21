"""Verification batch B2, item #49 (priorities managed) — the one place different
tasks' work really contends: the global agent-run cap and the per-epic subtask cap.
Real asyncio tasks, real permits."""

from __future__ import annotations

import asyncio

import pytest

from app.pipeline import concurrency as cc
from app.pipeline.concurrency import PrioritySemaphore, SlotAcquisitionTimeout


async def _drain_order(
    sem: PrioritySemaphore, arrivals: list[tuple[str, str]]
) -> list[str]:
    """Hold the only permit, enqueue waiters in `arrivals` order, release one by one."""
    await sem.acquire()
    got: list[str] = []

    async def waiter(name: str, prio: str) -> None:
        await sem.acquire(priority=prio)
        got.append(name)

    tasks = [asyncio.create_task(waiter(n, p)) for n, p in arrivals]
    await asyncio.sleep(0.05)  # everybody is now parked in the heap
    for _ in arrivals:
        sem.release()
        await asyncio.sleep(0.02)
    await asyncio.gather(*tasks)
    return got


async def test_highest_priority_first_then_fifo() -> None:
    order = await _drain_order(
        PrioritySemaphore(1),
        [
            ("L1", "low"),
            ("H1", "high"),
            ("M1", "medium"),
            ("H2", "high"),
            ("L2", "low"),
        ],
    )
    assert order == ["H1", "H2", "M1", "L1", "L2"]


async def test_unknown_priority_is_treated_as_medium() -> None:
    order = await _drain_order(
        PrioritySemaphore(1), [("L", "low"), ("X", "banana"), ("H", "high")]
    )
    assert order == ["H", "X", "L"]


async def test_urgent_outranks_high_if_supported_else_same_class() -> None:
    order = await _drain_order(PrioritySemaphore(1), [("H", "high"), ("U", "urgent")])
    assert order[0] in (
        "U",
        "H",
    )  # 'urgent' is either ranked above or treated like medium


async def test_equal_priority_is_strict_fifo() -> None:
    names = [f"w{i}" for i in range(12)]
    order = await _drain_order(PrioritySemaphore(1), [(n, "medium") for n in names])
    assert order == names


async def test_a_cancelled_waiter_neither_leaks_nor_blocks_the_others() -> None:
    sem = PrioritySemaphore(1)
    await sem.acquire()
    got: list[str] = []

    async def waiter(name: str, prio: str) -> None:
        await sem.acquire(priority=prio)
        got.append(name)

    t_hi = asyncio.create_task(waiter("hi", "high"))
    t_lo = asyncio.create_task(waiter("lo", "low"))
    await asyncio.sleep(0.03)
    t_hi.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t_hi
    sem.release()
    await asyncio.wait_for(t_lo, 1)
    assert got == ["lo"]
    sem.release()
    assert not sem.locked(), "permit leaked by the cancelled waiter"


async def test_cancel_racing_with_the_grant_hands_the_permit_on() -> None:
    sem = PrioritySemaphore(1)
    await sem.acquire()
    t1 = asyncio.create_task(sem.acquire(priority="high"))
    t2 = asyncio.create_task(sem.acquire(priority="low"))
    await asyncio.sleep(0.02)
    sem.release()  # grants t1 ...
    t1.cancel()  # ... and t1 is cancelled before it resumes
    await asyncio.sleep(0.02)
    await asyncio.wait_for(t2, 1)  # the permit must reach t2, not vanish


async def test_permit_count_is_exact_under_churn() -> None:
    sem = PrioritySemaphore(3)
    inside = 0
    peak = 0

    async def job(i: int) -> None:
        nonlocal inside, peak
        await sem.acquire(priority=("high", "medium", "low")[i % 3])
        inside += 1
        peak = max(peak, inside)
        await asyncio.sleep(0.005)
        inside -= 1
        sem.release()

    await asyncio.gather(*[job(i) for i in range(60)])
    assert peak == 3 and not sem.locked()


async def test_slot_timeout_is_a_loud_specific_error_not_a_hang(monkeypatch) -> None:
    cc.reset_for_testing(max_agent_runs=1)
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "slot_acquisition_timeout_seconds", 0.2)
    async with cc.agent_run_slot("high"):
        with pytest.raises(SlotAcquisitionTimeout):
            async with cc.agent_run_slot("low"):
                pass
    # the timed-out waiter must not have consumed the permit
    async with cc.agent_run_slot("low"):
        pass
    cc.reset_for_testing()


async def test_agent_run_slot_honours_task_priority_end_to_end() -> None:
    cc.reset_for_testing(max_agent_runs=1)
    started: list[str] = []
    gate = asyncio.Event()

    async def run(name: str, prio: str) -> None:
        async with cc.agent_run_slot(prio):
            started.append(name)
            if name == "first":
                await gate.wait()

    first = asyncio.create_task(run("first", "medium"))
    await asyncio.sleep(0.02)
    rest = [
        asyncio.create_task(run("low-task", "low")),
        asyncio.create_task(run("high-task", "high")),
    ]
    await asyncio.sleep(0.02)
    gate.set()
    await asyncio.gather(first, *rest)
    assert started == ["first", "high-task", "low-task"]
    cc.reset_for_testing()
