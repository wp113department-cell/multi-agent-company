"""Queue adapter interface — abstract base + AsyncioQueueAdapter (default).

Swap backends by setting QUEUE_BACKEND=bullmq (requires Redis).
The BullMQQueueAdapter stub documents the interface; replace the body
with redis+bullmq client calls when Redis becomes available.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from typing import Any, Callable

logger = logging.getLogger(__name__)

JobFn = Callable[..., Coroutine[Any, Any, Any]]


class QueueAdapter(ABC):
    """Abstract queue — enqueue a coroutine function with kwargs."""

    @abstractmethod
    async def enqueue(self, job_fn: JobFn, **kwargs: Any) -> str:
        """Schedule job_fn(**kwargs) and return a job ID."""

    @abstractmethod
    async def get_status(self, job_id: str) -> str:
        """Return job status: pending | running | completed | failed."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully drain and close the queue."""


class AsyncioQueueAdapter(QueueAdapter):
    """In-process asyncio queue — zero external dependencies."""

    def __init__(self, max_workers: int = 10) -> None:
        self._queue: asyncio.Queue[tuple[str, JobFn, dict[str, Any]]] = asyncio.Queue()
        self._statuses: dict[str, str] = {}
        self._max_workers = max_workers
        self._workers: list[asyncio.Task[None]] = []
        self._started = False

    async def _start(self) -> None:
        if not self._started:
            self._workers = [
                asyncio.create_task(self._worker(), name=f"queue-worker-{i}")
                for i in range(self._max_workers)
            ]
            self._started = True

    async def _worker(self) -> None:
        while True:
            job_id, fn, kwargs = await self._queue.get()
            self._statuses[job_id] = "running"
            try:
                await fn(**kwargs)
                self._statuses[job_id] = "completed"
            except Exception:
                logger.exception("Job %s failed", job_id)
                self._statuses[job_id] = "failed"
            finally:
                self._queue.task_done()

    async def enqueue(self, job_fn: JobFn, **kwargs: Any) -> str:
        await self._start()
        import uuid

        job_id = str(uuid.uuid4())
        self._statuses[job_id] = "pending"
        await self._queue.put((job_id, job_fn, kwargs))
        logger.debug("Enqueued job %s -> %s", job_id, job_fn.__name__)
        return job_id

    async def get_status(self, job_id: str) -> str:
        return self._statuses.get(job_id, "unknown")

    async def shutdown(self) -> None:
        await self._queue.join()
        for w in self._workers:
            w.cancel()
        self._workers = []
        self._started = False


class BullMQQueueAdapter(QueueAdapter):
    """Stub — replace with bullmq-python client when Redis is available.

    Enable by setting QUEUE_BACKEND=bullmq in environment.
    """

    async def enqueue(self, job_fn: JobFn, **kwargs: Any) -> str:
        raise NotImplementedError(
            "BullMQQueueAdapter requires Redis. Set QUEUE_BACKEND=asyncio or "
            "install redis and implement this body with bullmq-python."
        )

    async def get_status(self, job_id: str) -> str:
        raise NotImplementedError("BullMQQueueAdapter not implemented")

    async def shutdown(self) -> None:
        pass


def get_queue_adapter() -> QueueAdapter:
    """Return the configured queue adapter singleton."""
    from app.config import get_settings

    backend = get_settings().queue_backend.lower()
    if backend == "bullmq":
        return BullMQQueueAdapter()
    return AsyncioQueueAdapter()


_adapter: QueueAdapter | None = None


def queue() -> QueueAdapter:
    """Module-level singleton — one adapter per process."""
    global _adapter
    if _adapter is None:
        _adapter = get_queue_adapter()
    return _adapter
