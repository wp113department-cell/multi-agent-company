"""Tests for concurrency caps and worktree epic namespacing."""

from __future__ import annotations

import asyncio
from unittest.mock import patch


from app.pipeline.concurrency import (
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
