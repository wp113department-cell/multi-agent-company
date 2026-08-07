"""Queue adapter interface — abstract base + AsyncioQueueAdapter (default).

Swap backends via QUEUE_BACKEND:
- asyncio (default) — in-process, zero external dependencies.
- rq — real Redis Queue, bridged onto this async interface by RQAdapterBridge
  (wraps app.queue.rq_adapter.RQQueueAdapter, which is real, tested code).
- bullmq — still an intentional stub; requires a bullmq-python client that
  doesn't exist yet. Set QUEUE_BACKEND=asyncio or rq instead.

NOT WIRED INTO REAL TASK DISPATCH (Audit 04 finding ORCH-04-016, documented
rather than force-wired): every real task-launch call site in api/tasks.py
(run/restart/approve/pipeline_approve/push) dispatches via FastAPI's
BackgroundTasks.add_task(...) directly, not queue().enqueue(...) — so
QUEUE_BACKEND=rq currently has no effect on real task dispatch. This is
intentionally left as infrastructure-not-yet-integrated rather than force-
wired during the Audit 04 fix pass: BackgroundTasks (fire-and-forget within
the request's own process, no retry/persistence across a restart) and a real
queue worker (a separate process, survives app restarts, has its own retry
policy) have materially different failure semantics — swapping the real
dispatch call sites to use this adapter is a deliberate architectural
decision about which failure model the whole task lifecycle wants, not a
one-line wiring fix, and shouldn't be made as a drive-by change alongside
unrelated orchestration fixes. Same category prompt_registry.deploy() used
to be in before gap-closure Day 50 gave it a real caller (see
app/agents/tools.py::_propose_and_deploy_role_prompt) — deliberately
unintegrated infrastructure, not a bug, until a specific caller is chosen.
See docs/reports/AUDIT_04_ORCHESTRATION.md.
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
                # AUDIT_Q_BATCH08 §102 "Long-Running Jobs": bounded to the
                # same wall-clock timeout dispatch_job() applies to the real
                # BackgroundTasks dispatch path below, for defense-in-depth
                # on any caller that enqueues here directly.
                from app.config import get_settings

                await asyncio.wait_for(
                    fn(**kwargs), timeout=get_settings().job_wall_clock_timeout_seconds
                )
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


def _run_coroutine_job(job_fn: JobFn, kwargs: dict[str, Any]) -> Any:
    """RQ worker entrypoint. RQ workers run in separate processes and only
    know how to call plain sync functions by pickled reference — they cannot
    invoke an async job_fn directly (calling it would just return an
    un-awaited coroutine object). This module-level function is what RQ
    actually pickles/dispatches; job_fn and kwargs travel as its arguments
    and get awaited here, inside the worker, via asyncio.run()."""
    return asyncio.run(job_fn(**kwargs))


class RQAdapterBridge(QueueAdapter):
    """Adapts app.queue.rq_adapter.RQQueueAdapter (real, Redis-backed RQ) to
    this module's async QueueAdapter interface. The RQ adapter itself is
    unmodified — this bridge only translates calling convention and job
    status vocabulary so QUEUE_BACKEND=rq is actually reachable from
    get_queue_adapter() below (previously it silently fell through to
    AsyncioQueueAdapter no matter what QUEUE_BACKEND was set to, since this
    function never checked for "rq")."""

    _STATUS_MAP: dict[str, str] = {
        "created": "pending",
        "queued": "pending",
        "deferred": "pending",
        "scheduled": "pending",
        "started": "running",
        "finished": "completed",
        "failed": "failed",
        "stopped": "failed",
        "canceled": "failed",
    }

    def __init__(self) -> None:
        from app.queue.rq_adapter import get_rq_adapter

        self._adapter = get_rq_adapter()

    async def enqueue(self, job_fn: JobFn, **kwargs: Any) -> str:
        job = await asyncio.to_thread(
            self._adapter.enqueue, _run_coroutine_job, job_fn, kwargs
        )
        return str(job.id)

    async def get_status(self, job_id: str) -> str:
        def _fetch_status() -> str:
            from rq.exceptions import NoSuchJobError
            from rq.job import Job

            try:
                job = Job.fetch(job_id, connection=self._adapter.connection)
            except NoSuchJobError:
                return "unknown"
            return self._STATUS_MAP.get(job.get_status(refresh=True).value, "unknown")

        return await asyncio.to_thread(_fetch_status)

    async def shutdown(self) -> None:
        # RQ workers are separate, externally-managed processes (started via
        # `rq worker gridiron-high gridiron-default`, per rq_adapter.py's own
        # docstring) — there is no in-process worker pool here to drain.
        pass


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
    if backend == "rq":
        return RQAdapterBridge()
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


def _with_wall_clock_timeout(job_fn: JobFn, timeout: float) -> JobFn:
    """AUDIT_Q_BATCH08 §102 "Long-Running Jobs": app.queue.rq_adapter's
    RQQueueAdapter already bounds every job to _DEFAULT_JOB_TIMEOUT (30 min)
    — but only QUEUE_BACKEND=rq goes through that adapter. The default
    QUEUE_BACKEND=asyncio path below (FastAPI BackgroundTasks) had no
    wall-clock bound at all, only max_turns's turn-count limit — so
    whether a genuinely runaway job is ever killed silently depended on
    which backend an operator happened to configure. Wraps job_fn so BOTH
    paths share the same real bound (job_wall_clock_timeout_seconds,
    default 1800s to match RQ's own default) rather than force-wiring every
    task-launch site onto the RQ adapter (a bigger, separate architectural
    decision — see this module's own header docstring on why real dispatch
    still goes through BackgroundTasks by default)."""

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.wait_for(job_fn(*args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                "Job %s exceeded wall-clock timeout of %.0fs — cancelled. "
                "Its underlying task_id/agent_run (if any) will surface as "
                "failed via the existing orphan-recovery heartbeat sweep "
                "(app/fleet/failure_ladder.py::reconcile_orphaned_runs).",
                getattr(job_fn, "__name__", repr(job_fn)),
                timeout,
            )
            raise

    _wrapped.__name__ = getattr(job_fn, "__name__", "job_fn")
    return _wrapped


async def dispatch_job(
    background_tasks: Any,
    job_fn: JobFn,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Blocker 8 (audit_v1.md 4.7/4.8): the real fix for "every real
    task-launch call site dispatches via BackgroundTasks.add_task(), so
    QUEUE_BACKEND=rq has zero effect on real processing regardless of
    setting." This is the one real chokepoint every task-launch endpoint in
    api/tasks.py now calls instead of BackgroundTasks.add_task() directly.

    QUEUE_BACKEND=rq -> a real, persistent, retried (queue_job_retry_max)
    Redis Queue job that survives this process restarting, already bounded
    by RQQueueAdapter's own job_timeout.
    QUEUE_BACKEND=asyncio (default) -> fire-and-forget within this request's
    own process via FastAPI's BackgroundTasks, now wrapped in the same
    wall-clock bound RQ already had (AUDIT_Q_BATCH08 §102) — otherwise
    unchanged pre-existing behavior for any job that finishes within it.
    """
    from app.config import get_settings

    if get_settings().queue_backend.lower() == "rq":
        await queue().enqueue(job_fn, *args, **kwargs)
    else:
        wrapped = _with_wall_clock_timeout(
            job_fn, get_settings().job_wall_clock_timeout_seconds
        )
        background_tasks.add_task(wrapped, *args, **kwargs)


async def sweep_failed_rq_jobs() -> int:
    """Blocker 8 / Phase O finding #2 (audit_v1.md 4.7): "No retry
    configuration on RQ jobs, and no dead-letter handling code ... A failed
    job goes into RQ's own registry with no automatic retry and no
    application code ever reads it — effectively a silent drop."

    Retry is now real (see RQQueueAdapter.enqueue's `retry=Retry(...)`).
    This closes the second half: a periodic sweep — mirroring the existing
    orphan-run-recovery loop's own pattern in fleet/failure_ladder.py —
    reading RQ's FailedJobRegistry for jobs that exhausted their retries and
    recording each as a structured, queryable failed_events row (via the
    real app.event_bus.bus._write_failed_event, the same function the
    in-process event bus itself uses for its own retry exhaustion) instead
    of leaving it to silently sit in Redis with nothing surfacing it.

    Async + a fresh, disposed-after-use DB engine per call — never the
    shared app.db.session singleton from a background-loop context (see
    fleet/failure_ladder.py's own _new_isolated_db_engine for the same
    pattern and the reasoning: reusing one engine across independent
    asyncio.run()-style call boundaries raises "attached to a different
    loop").

    Returns the number of failed jobs recorded this sweep. Safe to call
    repeatedly — FailedJobRegistry.remove() below both records and drains
    each job, so a job is never recorded twice.
    """
    from app.config import get_settings

    if get_settings().queue_backend.lower() != "rq":
        return 0

    from rq.job import Job
    from rq.registry import FailedJobRegistry
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.event_bus.bus import _write_failed_event
    from app.event_bus.models import GridironEvent
    from app.queue.rq_adapter import get_rq_adapter

    adapter = get_rq_adapter()
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    recorded = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for queue_name, rq_queue in (
                ("gridiron-high", adapter._high),
                ("gridiron-default", adapter._default),
            ):
                registry = FailedJobRegistry(queue=rq_queue)
                for job_id in registry.get_job_ids():
                    try:
                        job = Job.fetch(job_id, connection=adapter.connection)
                    except Exception:
                        registry.remove(job_id)
                        continue
                    event = GridironEvent(
                        event_type="rq_job_failed",
                        payload={
                            "job_id": job_id,
                            "queue": queue_name,
                            "func_name": getattr(job, "func_name", "unknown"),
                            "exc_info": (job.exc_info or "")[-2000:],
                        },
                        emitted_by="rq_failed_job_sweep",
                    )
                    await _write_failed_event(
                        event,
                        handler_name="rq_worker",
                        error=f"RQ job {job_id} exhausted its retries on {queue_name}",
                        db=session,
                    )
                    # Drain from the registry either way — leaving it there
                    # forever would just mean re-recording the same job on
                    # every future sweep.
                    registry.remove(job)
                    recorded += 1
    finally:
        await engine.dispose()
    return recorded
