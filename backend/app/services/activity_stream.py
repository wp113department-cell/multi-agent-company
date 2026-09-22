"""Activity Stream — per-task SSE event bus.

Every run_agent_graph() call pushes typed events here. The SSE endpoint
(/api/tasks/{id}/stream) drains the queue and sends them to the browser.

Event types:
  thinking    — planner_node output (agent is reasoning)
  tool_call   — tool about to be called
  tool_result — tool completed
  file_edit   — write_file / edit_file detected
  terminal    — bash command + output
  agent_switch — role_name changed mid-pipeline
  token_usage — cumulative token count (periodic)
  stopped     — user clicked Stop; includes checkpoint_id
  done        — agent graph completed; includes AgentResult summary
  error       — unrecoverable failure
  context_trimmed   — conversation was condensed via LLM summarization (Stage 1.5)
  approaching_limit — tokens_in crossed 80% of context_token_budget (Stage 1.5)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)


def _call_sync_db_bridge(fn: Any, *args: Any) -> Any:
    """Safely calls one of app.db.repository's `*_sync` bridges (each does
    its own internal `asyncio.run(...)`, which requires the calling thread to
    have NO running event loop) from either of this module's two real
    calling contexts:

      1. A pure-sync thread with no running loop — e.g. base_graph.py's
         call_llm node, itself always invoked via asyncio.to_thread() by
         every real caller. Calls `fn` directly (unchanged fast path,
         asyncio.run() works exactly as it does for every other *_sync
         bridge already established elsewhere in the codebase).
      2. A FastAPI async route handler (app/api/activity.py's stop_task/
         resume_task/cancel_task) calling a TaskStream method directly,
         synchronously, from inside an ALREADY-running event loop — where
         `fn`'s own asyncio.run() would raise "cannot be called from a
         running event loop". Found live by this change's own test suite
         (test_b2_stop_cancel_restart.py): the exception was being silently
         swallowed by the write-through helpers' broad except-Exception, so
         a Stop/Resume set through the real API never actually reached the
         durable table at all — the one case this table exists for.
         Runs `fn` on a worker thread (which has no running loop of its own)
         and BLOCKS for the result — a Stop/Resume/Cancel is a rare,
         human-triggered action where a confirmed durable write matters more
         than shaving a DB round-trip off the response, and blocking here
         also closes a real race a fire-and-forget version of this had: a
         caller checking should_abort() immediately after set_abort() must
         see the write that already logically happened.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args)  # no loop running in this thread — safe as-is

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args).result(timeout=10)

# Gap-closure Stage 3 Day 62 (PLAN.md, "frontend behavior under real
# concurrent load/multiple sessions") — real measurement (not assumed)
# found that two concurrent subscribe() calls on the same TaskStream were
# competing consumers on one asyncio.Queue: pushing 6 events to a stream
# with two active subscribers delivered events 0-2 to subscriber A and 3-5
# to subscriber B, never all 6 to both. Any real "multiple sessions" case —
# two browser tabs on the same task's activity feed, or two dashboard
# viewers sharing app/api/fleet_dashboard.py's single `_DASHBOARD_STREAM_KEY`
# stream — silently saw an incomplete, randomly-split feed. Fixed by giving
# each subscribe() call its own queue (real fan-out) while preserving the
# single-subscriber tests' existing "push before subscribe is still seen"
# expectation via a bounded history replay every new subscriber gets before
# joining the live broadcast — same effective behavior for the pre-existing
# one-subscriber-arrives-late case this module was already tested for,
# correct behavior added for the untested concurrent-subscriber case.
_HISTORY_MAXLEN = 500
_SUBSCRIBER_QUEUE_MAXSIZE = 500


class TaskStream:
    """Holds per-subscriber queues (fan-out) and abort/resume state for one
    task run. `push()` broadcasts to every currently-subscribed queue and
    records the event in a bounded history so a subscriber that joins after
    some events were already pushed still sees them (matches this module's
    pre-existing single-subscriber semantics — see the Day 62 note above for
    why this is no longer a single shared queue)."""

    def __init__(self, task_id: str | int, *, durable: bool = False) -> None:
        self.task_id = str(task_id)
        self._history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAXLEN)
        self._subscriber_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._state_lock = threading.Lock()
        self._abort_event = threading.Event()
        self._resume_payload: dict[str, Any] | None = None
        self._started_at = time.time()
        self.tokens_in: int = 0
        self.tokens_out: int = 0
        # T2-B2 (2026-09-22, GRIDIRON_PARTIAL #234) — durable=True (only ever
        # passed by ActivityStreamRegistry.create()/get_or_create(), the sole
        # real production construction path — confirmed no other in-tree
        # caller constructs TaskStream directly) backs the abort/resume
        # signal with the real task_control_flags table so it survives a
        # process crash/restart. durable=False (the default, used by every
        # existing test that constructs a bare TaskStream() to unit-test its
        # pure in-memory behavior in isolation) keeps this a plain
        # in-process primitive with zero DB I/O — real bug caught by this
        # change's own test suite: an earlier version made EVERY TaskStream
        # durable unconditionally, which made tests/test_activity_stream.py's
        # own literal, reused ids ("t2") leak real stop_requested=True rows
        # into the shared Postgres dev DB across separate test runs, later
        # failing an unrelated test's "assert not stream.should_abort()" on
        # a supposedly-fresh stream.
        self._durable = durable
        # Has this process ever locally observed/set the abort flag for this
        # task_id? None means "no local write yet" (a freshly-created
        # TaskStream — either the very first one ever, or a fresh one in a
        # NEW process after a restart) — should_abort() below does exactly
        # one cold DB read in that case (durable=True only) to pick up a
        # flag a PREVIOUS process may have persisted before crashing, then
        # caches the answer locally so every subsequent per-turn check
        # (call_llm runs this every turn) stays in-memory, same latency as
        # before this change.
        self._abort_db_synced = False

    def push(self, event: dict[str, Any]) -> None:
        """Thread-safe push. Called from sync agent code (base_graph.py).
        Broadcasts to every live subscriber queue; a queue that's full
        (a slow/stalled subscriber) drops this event for that subscriber
        only, same as the prior single-queue behavior's own drop-on-full
        handling, now scoped per-subscriber instead of fleet-wide."""
        event.setdefault("task_id", self.task_id)
        event.setdefault("ts", time.time())
        with self._state_lock:
            self._history.append(event)
            queues = list(self._subscriber_queues)
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "ActivityStream queue full for task %s — dropping event %s "
                    "for one subscriber",
                    self.task_id,
                    event.get("type"),
                )

    def set_abort(self) -> None:
        self._abort_event.set()
        self._abort_db_synced = True
        self._write_through_stop(True)

    def should_abort(self) -> bool:
        if self._abort_event.is_set():
            return True
        if not self._abort_db_synced:
            # Cold cache: this is the first check this process has ever made
            # for this task_id. Consult the durable flag once — this is what
            # makes a Stop set by a process that then crashed still take
            # effect once a fresh process (re-)creates this TaskStream,
            # instead of silently defaulting to "not aborted" forever.
            self._abort_db_synced = True
            if self._read_through_stop():
                self._abort_event.set()
                return True
        return False

    def clear_abort(self) -> None:
        self._abort_event.clear()
        self._abort_db_synced = True
        self._write_through_stop(False)

    def set_resume(self, message: str, files: list[dict[str, Any]]) -> None:
        self._abort_event.clear()
        self._abort_db_synced = True
        self._resume_payload = {"message": message, "files": files}
        self._write_through_resume(message, files)

    def pop_resume(self) -> dict[str, Any] | None:
        payload = self._resume_payload
        self._resume_payload = None
        if payload is not None:
            # T2-B2 (#234) real bug caught by this change's own test suite
            # (test_activity_stream.py::test_resume_clears_abort): popping
            # only the in-memory copy left the durable row's resume_message
            # untouched, so a SECOND pop_resume() in the same process (or a
            # fresh one after a restart) re-delivered the same message from
            # the read-through fallback below. The durable row must be
            # cleared on every consume, not only on the cold-cache path.
            self._read_and_clear_resume()
            return payload
        # Same cold-cache reasoning as should_abort(): a Resume queued by a
        # process that crashed before it could dispatch the resume is still
        # sitting in the durable table, waiting for whichever process next
        # asks. Consumed exactly once (pop, not read) either way.
        return self._read_and_clear_resume()

    # -- durable backing store (T2-B2, #234) ---------------------------------
    # Best-effort by construction, same non-fatal contract as every other
    # *_sync bridge in app/db/repository.py: a DB hiccup degrades this task's
    # control flags back to today's pure in-process behavior for the rest of
    # this process's life — it never raises into the agent loop or the
    # Stop/Resume API handlers.

    def _write_through_stop(self, stop_requested: bool) -> None:
        if not self._durable:
            return
        try:
            from app.db.repository import set_task_control_flag_stop_sync

            _call_sync_db_bridge(
                set_task_control_flag_stop_sync, self.task_id, stop_requested
            )
        except Exception:
            logger.debug(
                "TaskControlFlag write-through (stop) failed for task %s",
                self.task_id,
                exc_info=True,
            )

    def _write_through_resume(self, message: str, files: list[dict[str, Any]]) -> None:
        if not self._durable:
            return
        try:
            from app.db.repository import set_task_control_flag_resume_sync

            _call_sync_db_bridge(
                set_task_control_flag_resume_sync, self.task_id, message, files
            )
        except Exception:
            logger.debug(
                "TaskControlFlag write-through (resume) failed for task %s",
                self.task_id,
                exc_info=True,
            )

    def _read_through_stop(self) -> bool:
        if not self._durable:
            return False
        try:
            from app.db.repository import get_task_control_flag_sync

            flag = _call_sync_db_bridge(get_task_control_flag_sync, self.task_id)
            return bool(flag and flag.get("stop_requested"))
        except Exception:
            logger.debug(
                "TaskControlFlag read-through (stop) failed for task %s",
                self.task_id,
                exc_info=True,
            )
            return False

    def _read_and_clear_resume(self) -> dict[str, Any] | None:
        if not self._durable:
            return None
        try:
            from app.db.repository import pop_task_control_flag_resume_sync

            result: dict[str, Any] | None = _call_sync_db_bridge(
                pop_task_control_flag_resume_sync, self.task_id
            )
            return result
        except Exception:
            logger.debug(
                "TaskControlFlag read-through (resume) failed for task %s",
                self.task_id,
                exc_info=True,
            )
            return None

    async def subscribe(
        self, timeout: float = 60.0
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator — yields events until 'done', 'error', or
        'stopped'. Each call gets its own queue (real fan-out): concurrent
        subscribers on the same TaskStream each see every event, not a
        competing-consumer split. Replays the bounded history first so an
        event pushed before this subscriber joined is still seen."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAXSIZE
        )
        with self._state_lock:
            history_snapshot = list(self._history)
            self._subscriber_queues.append(queue)
        try:
            for event in history_snapshot:
                yield event
                if event.get("type") in ("done", "error", "stopped"):
                    return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    yield {"type": "ping", "ts": time.time()}
                    continue
                yield event
                if event.get("type") in ("done", "error", "stopped"):
                    break
        finally:
            with self._state_lock:
                if queue in self._subscriber_queues:
                    self._subscriber_queues.remove(queue)


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------


class ActivityStreamRegistry:
    """Thread-safe registry of TaskStream objects keyed by task_id (str)."""

    def __init__(self) -> None:
        self._streams: dict[str, TaskStream] = {}
        self._lock = threading.Lock()

    def create(self, task_id: str | int) -> TaskStream:
        key = str(task_id)
        # durable=True — this registry is the one real production
        # construction path (see TaskStream.__init__'s own docstring for why
        # bare TaskStream(...) in tests stays non-durable).
        stream = TaskStream(key, durable=True)
        with self._lock:
            self._streams[key] = stream
        return stream

    def get(self, task_id: str | int) -> TaskStream | None:
        return self._streams.get(str(task_id))

    def get_or_create(self, task_id: str | int) -> TaskStream:
        key = str(task_id)
        with self._lock:
            if key not in self._streams:
                self._streams[key] = TaskStream(key, durable=True)
            return self._streams[key]

    def remove(self, task_id: str | int) -> None:
        self._streams.pop(str(task_id), None)

    def push_event(self, task_id: str | int, event: dict[str, Any]) -> None:
        """Push an event to a task stream. No-op if stream does not exist."""
        stream = self.get(task_id)
        if stream is not None:
            stream.push(event)

    def set_abort(self, task_id: str | int) -> bool:
        """Set abort flag. Returns True if stream existed."""
        stream = self.get(task_id)
        if stream is None:
            return False
        stream.set_abort()
        return True

    def should_abort(self, task_id: str | int) -> bool:
        # T2-B2 (#234) — get_or_create(), not get(): a fresh process (after a
        # crash/restart) that never locally created a stream for this
        # task_id must still be able to observe a stop flag a PREVIOUS
        # process persisted to the durable table before dying. get() alone
        # would return None here and silently skip TaskStream.should_abort()'s
        # own cold-DB-read entirely — this is the actual call shape
        # base_graph.py's call_llm node uses every turn.
        return self.get_or_create(task_id).should_abort()

    def clear_abort(self, task_id: str | int) -> bool:
        """Drop a STALE abort flag before a run starts. The flag is only ever
        cleared by /resume, so a Stop or Cancel (or a stray Stop on an idle task)
        used to make every LATER run of that task abort at its first LLM call and
        "finish" doing no work, until the server restarted. Returns whether a flag
        was actually set."""
        # get_or_create(), not get() — same T2-B2 reasoning as should_abort()
        # above: a STALE flag can exist in the durable table with no
        # in-process stream yet (e.g. right after a restart, before this
        # task's next run has created one), and this exact check is what a
        # fresh run relies on to not immediately abort on its very first
        # turn.
        stream = self.get_or_create(task_id)
        if not stream.should_abort():
            return False
        stream.clear_abort()
        return True


_registry: ActivityStreamRegistry | None = None
_registry_lock = threading.Lock()


def get_activity_registry() -> ActivityStreamRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ActivityStreamRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Convenience helpers called from base_graph.py hooks
# ---------------------------------------------------------------------------


def push_thinking(task_id: str | int, content: str, agent: str) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "thinking",
            "content": content[:2000],
            "agent": agent,
        },
    )


def push_tool_call(
    task_id: str | int, tool: str, inp: dict[str, Any], call_id: str = ""
) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "tool_call",
            "tool": tool,
            "input": inp,
            "id": call_id,
        },
    )


def push_tool_result(
    task_id: str | int, tool: str, preview: str, ok: bool, call_id: str = ""
) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "tool_result",
            "tool": tool,
            "preview": preview[:500],
            "ok": ok,
            "id": call_id,
        },
    )


def push_file_edit(task_id: str | int, path: str, action: str) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "file_edit",
            "path": path,
            "action": action,
        },
    )


def push_terminal(
    task_id: str | int, command: str, output: str, exit_code: int = 0
) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "terminal",
            "command": command,
            "output": output[:1000],
            "exit_code": exit_code,
        },
    )


def push_token_usage(task_id: str | int, tokens_in: int, tokens_out: int) -> None:
    cost = tokens_in * 0.000003 + tokens_out * 0.000015
    get_activity_registry().push_event(
        task_id,
        {
            "type": "token_usage",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 6),
        },
    )


def push_done(
    task_id: str | int, result: dict[str, Any], tokens_in: int, tokens_out: int
) -> None:
    cost = tokens_in * 0.000003 + tokens_out * 0.000015
    get_activity_registry().push_event(
        task_id,
        {
            "type": "done",
            "summary": str(result.get("summary", ""))[:300],
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 6),
        },
    )


def push_stopped(
    task_id: str | int, checkpoint_id: str, tokens_in: int, tokens_out: int
) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "stopped",
            "checkpoint_id": checkpoint_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        },
    )


def push_error(task_id: str | int, message: str, recoverable: bool = False) -> None:
    get_activity_registry().push_event(
        task_id,
        {
            "type": "error",
            "message": message,
            "recoverable": recoverable,
        },
    )


def push_agent_switch(task_id: str | int, agent: str, phase: str = "") -> None:
    """Day 18 — documented in this module's own docstring since it was
    written ("agent_switch — role_name changed mid-pipeline") but never
    implemented until now. Called at real pipeline node transitions
    (pm -> architect -> decomposer, and dev -> qa -> review in manager.py)."""
    get_activity_registry().push_event(
        task_id,
        {
            "type": "agent_switch",
            "agent": agent,
            "phase": phase,
        },
    )


def push_approval_required(task_id: str | int, thread_id: str, action: str) -> None:
    """Day 18 — fired right after Day 13/14's approval_gate.py records a new
    pending_approvals row, so the frontend activity feed can show it as a
    live, interactive card instead of only being discoverable on the
    separate /approvals page."""
    get_activity_registry().push_event(
        task_id,
        {
            "type": "approval_required",
            "thread_id": thread_id,
            "action": action,
        },
    )


def push_context_trimmed(
    task_id: str | int, messages_before: int, messages_after: int
) -> None:
    """Gap-closure Stage 1.5 (answers.md) — fired whenever
    base_graph.py::_condense_messages (or chat_agent.py's async
    equivalent) actually condenses the conversation, so the UI can show
    "earlier messages summarized" instead of the transcript silently
    getting shorter with no explanation."""
    get_activity_registry().push_event(
        task_id,
        {
            "type": "context_trimmed",
            "messages_before": messages_before,
            "messages_after": messages_after,
        },
    )


def push_approaching_limit(
    task_id: str | int, tokens_in: int, token_budget: int, pct: float
) -> None:
    """Gap-closure Stage 1.5 (answers.md) — fired once tokens_in crosses
    80% of the configured context_token_budget but before condensing
    actually triggers, so the UI can warn ahead of the cut rather than
    only after it happens."""
    get_activity_registry().push_event(
        task_id,
        {
            "type": "approaching_limit",
            "tokens_in": tokens_in,
            "token_budget": token_budget,
            "pct": round(pct, 3),
        },
    )
