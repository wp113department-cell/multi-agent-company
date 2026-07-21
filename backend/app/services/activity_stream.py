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
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-task stream state
# ---------------------------------------------------------------------------


class TaskStream:
    """Holds the asyncio.Queue and abort/resume state for one task run."""

    def __init__(self, task_id: str | int) -> None:
        self.task_id = str(task_id)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._abort_event = threading.Event()
        self._resume_payload: dict[str, Any] | None = None
        self._started_at = time.time()
        self.tokens_in: int = 0
        self.tokens_out: int = 0

    def push(self, event: dict[str, Any]) -> None:
        """Thread-safe push. Called from sync agent code (base_graph.py)."""
        event.setdefault("task_id", self.task_id)
        event.setdefault("ts", time.time())
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "ActivityStream queue full for task %s — dropping event %s",
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
        """Async generator — yields events until 'done', 'error', or 'stopped'."""
        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                yield {"type": "ping", "ts": time.time()}
                continue
            yield event
            if event.get("type") in ("done", "error", "stopped"):
                break


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
