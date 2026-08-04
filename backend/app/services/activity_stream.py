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

    def __init__(self, task_id: str | int) -> None:
        self.task_id = str(task_id)
        self._history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAXLEN)
        self._subscriber_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._state_lock = threading.Lock()
        self._abort_event = threading.Event()
        self._resume_payload: dict[str, Any] | None = None
        self._started_at = time.time()
        self.tokens_in: int = 0
        self.tokens_out: int = 0

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

    def should_abort(self) -> bool:
        return self._abort_event.is_set()

    def set_resume(self, message: str, files: list[dict[str, Any]]) -> None:
        self._abort_event.clear()
        self._resume_payload = {"message": message, "files": files}

    def pop_resume(self) -> dict[str, Any] | None:
        payload = self._resume_payload
        self._resume_payload = None
        return payload

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
        stream = TaskStream(key)
        with self._lock:
            self._streams[key] = stream
        return stream

    def get(self, task_id: str | int) -> TaskStream | None:
        return self._streams.get(str(task_id))

    def get_or_create(self, task_id: str | int) -> TaskStream:
        key = str(task_id)
        with self._lock:
            if key not in self._streams:
                self._streams[key] = TaskStream(key)
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
        stream = self.get(task_id)
        return stream.should_abort() if stream else False


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
