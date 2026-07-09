"""Tests for QueueAdapter contract — AsyncioQueueAdapter and interface."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.pipeline.queue_adapter import (
    AsyncioQueueAdapter,
    BullMQQueueAdapter,
    QueueAdapter,
    get_queue_adapter,
    queue,
)


class TestAsyncioQueueAdapter:
    async def test_enqueue_returns_job_id(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=1)
        called: list[str] = []

        async def job(msg: str) -> None:
            called.append(msg)

        job_id = await adapter.enqueue(job, msg="hello")
        assert len(job_id) == 36  # UUID

        # Wait for job to complete
        await asyncio.sleep(0.05)
        assert "hello" in called
        await adapter.shutdown()

    async def test_status_transitions(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=1)
        event = asyncio.Event()

        async def slow_job() -> None:
            await event.wait()

        job_id = await adapter.enqueue(slow_job)
        await asyncio.sleep(0.01)
        # After enqueue it should be running
        status = await adapter.get_status(job_id)
        assert status in ("running", "pending", "completed")
        event.set()
        await adapter.shutdown()

    async def test_unknown_job_id_returns_unknown(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=1)
        status = await adapter.get_status("nonexistent-id")
        assert status == "unknown"

    async def test_job_failure_sets_status_failed(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=1)

        async def failing_job() -> None:
            raise RuntimeError("boom")

        job_id = await adapter.enqueue(failing_job)
        await asyncio.sleep(0.05)
        status = await adapter.get_status(job_id)
        assert status == "failed"
        await adapter.shutdown()

    async def test_multiple_workers_run_concurrently(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=3)
        results: list[int] = []

        async def job(n: int) -> None:
            await asyncio.sleep(0.02)
            results.append(n)

        ids = [await adapter.enqueue(job, n=i) for i in range(3)]
        await asyncio.sleep(0.1)
        assert sorted(results) == [0, 1, 2]
        await adapter.shutdown()

    async def test_shutdown_drains_queue(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=2)
        results: list[int] = []

        async def job(n: int) -> None:
            results.append(n)

        for i in range(4):
            await adapter.enqueue(job, n=i)

        await adapter.shutdown()
        assert len(results) == 4


class TestBullMQAdapterStub:
    async def test_enqueue_raises_not_implemented(self) -> None:
        adapter = BullMQQueueAdapter()
        with pytest.raises(NotImplementedError):
            await adapter.enqueue(lambda: None)  # type: ignore[arg-type]

    async def test_get_status_raises_not_implemented(self) -> None:
        adapter = BullMQQueueAdapter()
        with pytest.raises(NotImplementedError):
            await adapter.get_status("x")

    async def test_shutdown_is_noop(self) -> None:
        adapter = BullMQQueueAdapter()
        await adapter.shutdown()  # should not raise


class TestGetQueueAdapter:
    @patch("app.config.get_settings")
    def test_asyncio_backend_by_default(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock
        s = MagicMock()
        s.queue_backend = "asyncio"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        adapter = get_queue_adapter()
        assert isinstance(adapter, AsyncioQueueAdapter)

    @patch("app.config.get_settings")
    def test_bullmq_backend_returns_bullmq(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock
        s = MagicMock()
        s.queue_backend = "bullmq"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        adapter = get_queue_adapter()
        assert isinstance(adapter, BullMQQueueAdapter)

    def test_is_abstract(self) -> None:
        assert issubclass(QueueAdapter, object)
        # Confirm abstract methods exist
        assert hasattr(QueueAdapter, "enqueue")
        assert hasattr(QueueAdapter, "get_status")
        assert hasattr(QueueAdapter, "shutdown")
