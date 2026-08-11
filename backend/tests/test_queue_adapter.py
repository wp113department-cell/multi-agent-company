"""Tests for QueueAdapter contract — AsyncioQueueAdapter and interface."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.queue_adapter import (
    AsyncioQueueAdapter,
    BullMQQueueAdapter,
    QueueAdapter,
    RQAdapterBridge,
    _run_coroutine_job,
    get_queue_adapter,
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
        # AUDIT_Q_BATCH16 §86 gap-closure: the worker now retries
        # (queue_job_retry_max, default 3) before giving up — patch it to 0
        # so this test still exercises the immediate terminal-failure path
        # without waiting through exponential backoff.
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.queue_job_retry_max = 0
            mock_settings.return_value.job_wall_clock_timeout_seconds = 30

            adapter = AsyncioQueueAdapter(max_workers=1)

            async def failing_job() -> None:
                raise RuntimeError("boom")

            job_id = await adapter.enqueue(failing_job)
            await asyncio.sleep(0.05)
            status = await adapter.get_status(job_id)
            assert status == "failed"
            await adapter.shutdown()

    async def test_job_retries_on_failure_then_succeeds(self) -> None:
        # AUDIT_Q_BATCH16 §86 gap-closure — "Retry": the in-process asyncio
        # backend previously had zero retry logic (unlike the RQ backend's
        # real Retry(max=...)); a job that fails once and then succeeds
        # should now end up "completed", not "failed" on the first error.
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.queue_job_retry_max = 2
            mock_settings.return_value.job_wall_clock_timeout_seconds = 30

            adapter = AsyncioQueueAdapter(max_workers=1)
            attempts: list[int] = []

            async def flaky_job() -> None:
                attempts.append(1)
                if len(attempts) < 2:
                    raise RuntimeError("transient")

            job_id = await adapter.enqueue(flaky_job)
            await asyncio.sleep(1.0)
            status = await adapter.get_status(job_id)
            assert status == "completed"
            assert len(attempts) == 2
            await adapter.shutdown()

    async def test_job_exhausts_retries_and_fails(self) -> None:
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.queue_job_retry_max = 1
            mock_settings.return_value.job_wall_clock_timeout_seconds = 30

            adapter = AsyncioQueueAdapter(max_workers=1)
            attempts: list[int] = []

            async def always_fails() -> None:
                attempts.append(1)
                raise RuntimeError("boom")

            job_id = await adapter.enqueue(always_fails)
            await asyncio.sleep(1.0)
            status = await adapter.get_status(job_id)
            assert status == "failed"
            assert len(attempts) == 2  # initial attempt + 1 retry
            await adapter.shutdown()

    async def test_enqueue_forwards_positional_args(self) -> None:
        # AUDIT_Q_BATCH16 §86 gap-closure — every real dispatch_job() call
        # site passes positional args (task_id, plan, repo_path, ...); the
        # interface must actually deliver them to job_fn.
        adapter = AsyncioQueueAdapter(max_workers=1)
        received: list[tuple[int, str]] = []

        async def job(task_id: int, msg: str) -> None:
            received.append((task_id, msg))

        await adapter.enqueue(job, 42, msg="hello")
        await asyncio.sleep(0.05)
        assert received == [(42, "hello")]
        await adapter.shutdown()

    async def test_multiple_workers_run_concurrently(self) -> None:
        adapter = AsyncioQueueAdapter(max_workers=3)
        results: list[int] = []

        async def job(n: int) -> None:
            await asyncio.sleep(0.02)
            results.append(n)

        ids = [await adapter.enqueue(job, n=i) for i in range(3)]  # noqa: F841
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


class TestRunCoroutineJob:
    """_run_coroutine_job is the module-level, RQ-picklable sync shim that
    lets a real RQ worker process run our async job functions."""

    def test_awaits_the_coroutine_and_returns_its_result(self) -> None:
        async def job(x: int, y: int) -> int:
            return x + y

        result = _run_coroutine_job(job, (), {"x": 2, "y": 3})
        assert result == 5

    def test_awaits_the_coroutine_with_positional_args(self) -> None:
        # AUDIT_Q_BATCH16 §86 gap-closure — positional args previously had
        # nowhere to travel through this shim at all.
        async def job(x: int, y: int) -> int:
            return x + y

        result = _run_coroutine_job(job, (2,), {"y": 3})
        assert result == 5

    def test_propagates_exceptions_from_the_coroutine(self) -> None:
        async def failing_job() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            _run_coroutine_job(failing_job, (), {})


class TestRQAdapterBridge:
    """RQAdapterBridge wraps app.queue.rq_adapter.RQQueueAdapter (real,
    Redis-backed) for the async QueueAdapter interface — mocked here so
    these tests never touch a real Redis server, matching this file's
    existing style of testing behavior without real infrastructure."""

    def _make_bridge(self, mock_rq_adapter: MagicMock) -> RQAdapterBridge:
        with patch("app.queue.rq_adapter.get_rq_adapter", return_value=mock_rq_adapter):
            return RQAdapterBridge()

    async def test_enqueue_delegates_to_rq_adapter_and_returns_job_id(self) -> None:
        mock_job = MagicMock()
        mock_job.id = "rq-job-123"
        mock_rq_adapter = MagicMock()
        mock_rq_adapter.enqueue.return_value = mock_job
        bridge = self._make_bridge(mock_rq_adapter)

        async def job_fn(task_id: int) -> None:
            pass

        job_id = await bridge.enqueue(job_fn, task_id=42)

        assert job_id == "rq-job-123"
        # The real async job_fn + its args/kwargs travel as arguments to the
        # RQ-picklable shim — RQ never receives job_fn as its own `fn`.
        # `priority` defaults to "default" and is passed as RQQueueAdapter's
        # own real queue-selection kwarg, never folded into job_fn's kwargs.
        mock_rq_adapter.enqueue.assert_called_once_with(
            _run_coroutine_job, job_fn, (), {"task_id": 42}, priority="default"
        )

    async def test_enqueue_forwards_positional_args_and_priority(self) -> None:
        # AUDIT_Q_BATCH16 §86 gap-closure — every real dispatch_job() call
        # site passes positional args AND a real DevTask.priority; both
        # previously either broke (TypeError on positional args) or were
        # silently dropped (priority never reached RQQueueAdapter's own
        # gridiron-high/gridiron-default queue selection).
        mock_job = MagicMock()
        mock_job.id = "rq-job-456"
        mock_rq_adapter = MagicMock()
        mock_rq_adapter.enqueue.return_value = mock_job
        bridge = self._make_bridge(mock_rq_adapter)

        async def job_fn(task_id: int, title: str) -> None:
            pass

        job_id = await bridge.enqueue(job_fn, 42, "some title", priority="high")

        assert job_id == "rq-job-456"
        mock_rq_adapter.enqueue.assert_called_once_with(
            _run_coroutine_job,
            job_fn,
            (42, "some title"),
            {},
            priority="high",
        )

    async def test_get_status_maps_rq_statuses(self) -> None:
        from rq.job import JobStatus

        cases = {
            JobStatus.CREATED: "pending",
            JobStatus.QUEUED: "pending",
            JobStatus.DEFERRED: "pending",
            JobStatus.SCHEDULED: "pending",
            JobStatus.STARTED: "running",
            JobStatus.FINISHED: "completed",
            JobStatus.FAILED: "failed",
            JobStatus.STOPPED: "failed",
            JobStatus.CANCELED: "failed",
        }
        mock_rq_adapter = MagicMock()
        bridge = self._make_bridge(mock_rq_adapter)

        for rq_status, expected in cases.items():
            mock_job = MagicMock()
            mock_job.get_status.return_value = rq_status
            with patch("rq.job.Job.fetch", return_value=mock_job):
                status = await bridge.get_status("some-id")
            assert status == expected, f"{rq_status} should map to {expected}"

    async def test_get_status_unknown_job_returns_unknown(self) -> None:
        from rq.exceptions import NoSuchJobError

        mock_rq_adapter = MagicMock()
        bridge = self._make_bridge(mock_rq_adapter)

        with patch("rq.job.Job.fetch", side_effect=NoSuchJobError()):
            status = await bridge.get_status("does-not-exist")

        assert status == "unknown"

    async def test_shutdown_is_a_noop(self) -> None:
        """RQ workers are separate, externally-started processes — nothing
        in-process for the bridge itself to drain or close."""
        mock_rq_adapter = MagicMock()
        bridge = self._make_bridge(mock_rq_adapter)
        await bridge.shutdown()  # should not raise


class TestGetQueueAdapter:
    @patch("app.config.get_settings")
    def test_asyncio_backend_by_default(self, mock_settings: object) -> None:
        from unittest.mock import MagicMock

        s = MagicMock()
        s.queue_backend = "asyncio"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        adapter = get_queue_adapter()
        assert isinstance(adapter, AsyncioQueueAdapter)

    @patch("app.queue.rq_adapter.get_rq_adapter")
    @patch("app.config.get_settings")
    def test_rq_backend_returns_rq_bridge(
        self, mock_settings: object, mock_get_rq_adapter: MagicMock
    ) -> None:
        """QUEUE_BACKEND=rq must actually reach RQAdapterBridge — previously
        this function only ever checked for "bullmq", so setting
        QUEUE_BACKEND=rq silently fell through to AsyncioQueueAdapter no
        matter what, even though config.py documents rq as a real option and
        a fully-built RQQueueAdapter already existed with zero callers."""
        s = MagicMock()
        s.queue_backend = "rq"
        (mock_settings if callable(mock_settings) else mock_settings).return_value = s  # type: ignore[union-attr]
        mock_get_rq_adapter.return_value = MagicMock()

        adapter = get_queue_adapter()

        assert isinstance(adapter, RQAdapterBridge)

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
