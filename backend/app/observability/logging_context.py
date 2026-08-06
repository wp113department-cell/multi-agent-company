"""Structured, trace-correlated logging.

Blocker (audit_v1.md 4.7 #2 / Phase M): "Logging is unstructured, plain-
text, and NOT trace_id-correlated despite the code's own documented design
claim ... fleet/metrics.py's own module docstring explicitly claims 'Every
run has a trace_id that correlates: bus events, logs, approvals,
checkpoints, rollbacks' — false for logs as implemented. An operator
grepping logs for a failing run has no trace_id anchor."

Design: contextvars (not thread-locals — these correctly propagate through
asyncio.to_thread()'s worker threads, which is exactly how run_agent_graph()
is dispatched from manager.py, per Python's documented context-propagation
behavior for to_thread) hold the current trace_id/task_id/agent_run_id.
bind_log_context() sets them for the duration of a `with` block (e.g. one
agent run); a logging.Filter attaches whatever is currently bound to every
LogRecord passing through, and JsonLogFormatter renders records (with
whatever correlation fields are present) as one JSON object per line —
grep/jq-friendly, and matches what "structured logging" means everywhere
else in this ecosystem.

This is deliberately NOT a rewrite of every logger.info() call site across
the codebase (hundreds of them) — that isn't what makes correlation work.
Binding context once at the real chokepoint each log-heavy code path
already funnels through (run_agent_graph, chat_agent, planning pipeline)
is what makes every log line emitted underneath it — including from
already-existing, unmodified logger calls — carry the right trace_id, for
free.
"""

from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)
task_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "task_id", default=""
)
agent_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_run_id", default=""
)


@contextmanager
def bind_log_context(
    trace_id: str = "", task_id: str = "", agent_run_id: str = ""
) -> Iterator[None]:
    """Bind correlation ids onto every log record emitted (from any module,
    without that module needing to know about this) for the duration of
    this block. Restores the previous values on exit — nesting is safe
    (e.g. a chat turn inside a session, or a subtask inside an epic)."""
    tokens = []
    if trace_id:
        tokens.append((trace_id_var, trace_id_var.set(trace_id)))
    if task_id:
        tokens.append((task_id_var, task_id_var.set(task_id)))
    if agent_run_id:
        tokens.append((agent_run_id_var, agent_run_id_var.set(agent_run_id)))
    try:
        yield
    finally:
        for var, token in tokens:
            var.reset(token)


class CorrelationFilter(logging.Filter):
    """Attaches the currently-bound trace_id/task_id/agent_run_id to every
    LogRecord. A no-op (empty string) when nothing is currently bound —
    never raises, never drops a log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        record.task_id = task_id_var.get()
        record.agent_run_id = agent_run_id_var.get()
        return True


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger name, message,
    plus trace_id/task_id/agent_run_id whenever CorrelationFilter has
    attached them (empty string when nothing was bound — an operator can
    still grep by logger/level/message on those lines, they just have no
    trace anchor, same honest degradation as before this fix for anything
    outside a bound context)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "task_id": getattr(record, "task_id", ""),
            "agent_run_id": getattr(record, "agent_run_id", ""),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_structured_logging(level: str) -> None:
    """Real entry point — call once at process startup (main.py's
    lifespan) instead of a bare logging.basicConfig(). Idempotent: clears
    any handlers a prior call (or pytest's own logging setup) attached to
    the root logger, so repeated calls (e.g. across test runs re-importing
    this module) don't accumulate duplicate handlers and double-log every
    line.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(CorrelationFilter())
    root.addHandler(handler)
