"""RQ (Redis Queue) adapter for Gridiron task dispatch.

Provides `RQQueueAdapter` — a drop-in replacement for the in-process asyncio
queue when `queue_backend=rq` is set in config.

Usage (from specialized_agents or pipeline):
    from app.queue.rq_adapter import get_rq_adapter
    adapter = get_rq_adapter()
    job = adapter.enqueue(fn, task_id=42, description="...", repo_path="/...")

The adapter is a thin wrapper. It does NOT start an RQ worker — that is an
infra concern and must be started separately:
    rq worker gridiron-high gridiron-default

Design notes:
- Two queues: "gridiron-high" (priority tasks) and "gridiron-default".
- Jobs time out after 30 minutes (configurable via QUEUE_JOB_TIMEOUT).
- Connection is a single Redis connection per process (singleton).
- No monkey-patching — the adapter is accessed explicitly.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.config import get_settings

logger = logging.getLogger(__name__)

_adapter_instance: "RQQueueAdapter | None" = None

_DEFAULT_JOB_TIMEOUT = 1800  # 30 minutes


class RQQueueAdapter:
    """Thin wrapper around rq.Queue that provides Gridiron-specific queue names."""

    def __init__(self, redis_url: str) -> None:
        import redis
        import rq

        self._conn = redis.from_url(redis_url, decode_responses=False)
        self._high: rq.Queue = rq.Queue("gridiron-high", connection=self._conn)
        self._default: rq.Queue = rq.Queue("gridiron-default", connection=self._conn)
        logger.info("RQQueueAdapter connected to %s", redis_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        fn: Callable[..., Any],
        *args: Any,
        priority: str = "default",
        job_timeout: int = _DEFAULT_JOB_TIMEOUT,
        **kwargs: Any,
    ) -> Any:
        """Enqueue fn(*args, **kwargs) on the selected priority queue.

        Returns the rq.Job object (has .id and .get_status()).
        """
        queue = self._high if priority == "high" else self._default
        job = queue.enqueue(fn, *args, job_timeout=job_timeout, **kwargs)
        logger.info(
            "Enqueued job %s fn=%s queue=%s",
            job.id,
            getattr(fn, "__name__", repr(fn)),
            queue.name,
        )
        return job

    def enqueue_agent(
        self,
        agent_name: str,
        task_id: int,
        description: str,
        repo_path: str | None = None,
        priority: str = "default",
    ) -> Any:
        """Convenience method to enqueue a specialized agent via the registry.

        Imports the agent fn at call time so the RQ worker process picks up the
        module correctly.
        """
        from app.api.specialized_agents import _load_agent_fn

        fn = _load_agent_fn(agent_name)
        return self.enqueue(
            fn,
            priority=priority,
            task_id=task_id,
            description=description,
            repo_path=repo_path,
        )

    def queue_sizes(self) -> dict[str, int]:
        """Return current queue depths for monitoring."""
        return {
            "gridiron-high": len(self._high),
            "gridiron-default": len(self._default),
        }

    def ping(self) -> bool:
        """Return True if Redis is reachable."""
        try:
            self._conn.ping()
            return True
        except Exception:
            return False


def get_rq_adapter() -> RQQueueAdapter:
    """Return the singleton RQQueueAdapter, creating it on first call."""
    global _adapter_instance
    if _adapter_instance is None:
        settings = get_settings()
        _adapter_instance = RQQueueAdapter(redis_url=settings.redis_url)
    return _adapter_instance


def reset_rq_adapter() -> None:
    """Reset the singleton (used in tests to inject a mock Redis URL)."""
    global _adapter_instance
    _adapter_instance = None
