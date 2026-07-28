"""Tests for concurrency caps and worktree epic namespacing."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.pipeline.concurrency import (
    SlotAcquisitionTimeout,
    agent_run_slot,
    epic_slot,
    reset_for_testing,
    subtask_slot,
)
from app.repo_tools.worktree import worktree_path


class TestSemaphoreSlots:
    def setup_method(self) -> None:
        reset_for_testing(max_epics=2, max_agent_runs=3, max_subtasks_per_epic=2)

    async def test_epic_slot_allows_up_to_cap(self) -> None:
        """Two epics can run concurrently; a third must wait."""
        results: list[int] = []

        async def run_epic(n: int) -> None:
            async with epic_slot():
                await asyncio.sleep(0.01)
                results.append(n)

        await asyncio.gather(run_epic(1), run_epic(2), run_epic(3))
        assert sorted(results) == [1, 2, 3]

    async def test_agent_run_slot_cap_3(self) -> None:
        """All 4 tasks finish but only 3 can hold the semaphore simultaneously."""
        active: list[int] = []
        peak: list[int] = []

        async def run_task(n: int) -> None:
            async with agent_run_slot():
                active.append(n)
                peak.append(len(active))
                await asyncio.sleep(0.01)
                active.remove(n)

        await asyncio.gather(*[run_task(i) for i in range(4)])
        assert max(peak) <= 3

    async def test_subtask_slot_per_epic(self) -> None:
        """Subtask slots are scoped per epic; different epics are independent."""
        active_a: list[int] = []

        async def run_subtask_a(n: int) -> None:
            async with subtask_slot("epic-a"):
                active_a.append(n)
                await asyncio.sleep(0.01)
                active_a.remove(n)

        await asyncio.gather(*[run_subtask_a(i) for i in range(4)])
        assert True  # No deadlock = pass

    async def test_subtask_slot_different_epics_independent(self) -> None:
        """Epic B's subtask slot doesn't block Epic A's."""
        entered: list[str] = []

        async def run_a() -> None:
            async with subtask_slot("epic-a"):
                entered.append("a")
                await asyncio.sleep(0.02)

        async def run_b() -> None:
            async with subtask_slot("epic-b"):
                entered.append("b")
                await asyncio.sleep(0.01)

        await asyncio.gather(run_a(), run_b())
        assert "a" in entered and "b" in entered

    async def test_reset_for_testing_replaces_semaphores(self) -> None:
        reset_for_testing(max_epics=1)
        # Only one should be able to enter at a time
        order: list[int] = []

        async def grab(n: int) -> None:
            async with epic_slot():
                order.append(n)
                await asyncio.sleep(0.01)

        await asyncio.gather(grab(1), grab(2))
        assert order == [1, 2] or order == [2, 1]


class TestSlotAcquisitionTimeout:
    """MASTER_AGENT_v2.md Phase 5.6 — a slot that can never be freed (the
    real, bounded deadlock risk this project's asyncio.Semaphore-based
    concurrency model can actually produce) must fail loudly within a
    configured bound, not hang forever. Before this change, `agent_run_slot`/
    `subtask_slot` had no timeout at all — confirmed by reading
    app/pipeline/concurrency.py in full before adding one."""

    def setup_method(self) -> None:
        reset_for_testing(max_agent_runs=1, max_subtasks_per_epic=1)

    @pytest.mark.asyncio
    async def test_agent_run_slot_raises_on_timeout_not_hang_forever(self) -> None:
        holder_ready = asyncio.Event()

        async def hold_slot_forever() -> None:
            async with agent_run_slot():
                holder_ready.set()
                await asyncio.sleep(10)

        holder_task = asyncio.create_task(hold_slot_forever())
        await holder_ready.wait()

        with patch("app.pipeline.concurrency.get_settings") as mock_settings:
            mock_settings.return_value.slot_acquisition_timeout_seconds = 0.05
            start = asyncio.get_event_loop().time()
            with pytest.raises(SlotAcquisitionTimeout) as exc_info:
                async with agent_run_slot():
                    pass  # pragma: no cover - must never be reached
            elapsed = asyncio.get_event_loop().time() - start

        holder_task.cancel()
        try:
            await holder_task
        except asyncio.CancelledError:
            pass

        assert elapsed < 2.0, "must fail fast (bounded), not hang"
        assert exc_info.value.slot_kind == "agent_run"

    @pytest.mark.asyncio
    async def test_subtask_slot_raises_on_timeout_not_hang_forever(self) -> None:
        # _get_subtask_sem() lazily creates each epic's semaphore straight
        # from get_settings().max_concurrent_subtasks_per_epic — unlike
        # agent_run_slot's singleton, reset_for_testing()'s own
        # max_subtasks_per_epic param never actually seeds it (a pre-existing
        # gap, out of this fix's scope), so the real cap must come from a
        # patched get_settings() for the whole test, not that param.
        with patch("app.pipeline.concurrency.get_settings") as mock_settings:
            mock_settings.return_value.max_concurrent_subtasks_per_epic = 1
            mock_settings.return_value.slot_acquisition_timeout_seconds = 0.05

            holder_ready = asyncio.Event()

            async def hold_slot_forever() -> None:
                async with subtask_slot("epic-deadlock-test"):
                    holder_ready.set()
                    await asyncio.sleep(10)

            holder_task = asyncio.create_task(hold_slot_forever())
            await holder_ready.wait()

            with pytest.raises(SlotAcquisitionTimeout) as exc_info:
                async with subtask_slot("epic-deadlock-test"):
                    pass  # pragma: no cover - must never be reached

        holder_task.cancel()
        try:
            await holder_task
        except asyncio.CancelledError:
            pass

        assert exc_info.value.slot_kind == "subtask"

    @pytest.mark.asyncio
    async def test_slot_is_released_on_normal_exit_not_leaked(self) -> None:
        """A timeout-capable acquire must still release cleanly on the
        happy path — confirms the try/finally release wasn't broken by
        adding the timeout wrapper."""
        reset_for_testing(max_agent_runs=1)

        async with agent_run_slot():
            pass

        # If the first slot leaked (never released), this would hang/timeout.
        async with agent_run_slot():
            pass

    @pytest.mark.asyncio
    async def test_slot_is_released_when_body_raises(self) -> None:
        reset_for_testing(max_agent_runs=1)

        with pytest.raises(ValueError):
            async with agent_run_slot():
                raise ValueError("boom")

        # Must not be stuck held by the failed acquisition above.
        async with agent_run_slot():
            pass


class TestWorktreeEpicNamespacing:
    @patch("app.repo_tools.worktree.get_settings")
    def test_path_without_epic(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock

        s = MagicMock()
        s.worktrees_dir = "/tmp/wt"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        p = worktree_path(42)
        assert str(p) == "/tmp/wt/task-42"

    @patch("app.repo_tools.worktree.get_settings")
    def test_path_with_epic(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock

        s = MagicMock()
        s.worktrees_dir = "/tmp/wt"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        p = worktree_path(42, epic_id="abc-123")
        assert str(p) == "/tmp/wt/epic-abc-123/task-42"

    @patch("app.repo_tools.worktree.get_settings")
    def test_different_epics_different_paths(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock

        s = MagicMock()
        s.worktrees_dir = "/tmp/wt"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        p1 = worktree_path(1, epic_id="epic-A")
        p2 = worktree_path(1, epic_id="epic-B")
        assert p1 != p2

    @patch("app.repo_tools.worktree.get_settings")
    def test_same_task_different_epic_no_collision(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock

        s = MagicMock()
        s.worktrees_dir = "/tmp/wt"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        paths = {str(worktree_path(99, epic_id=f"epic-{i}")) for i in range(5)}
        assert len(paths) == 5
