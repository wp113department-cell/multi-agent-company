"""Gap-closure Day 22 (Stage 1.3, answers.md) — a real circuit breaker
around Anthropic/Groq LLM client calls.

Before this, a real provider outage (Anthropic/Groq down or rate-limiting
hard) had no fleet-wide circuit: every one of the ~74-76 agent modules
(each running in its own asyncio.to_thread worker thread, per
base_graph.py's run_agent_graph) would keep calling the API independently,
each hitting its own per-call llm_call_timeout_seconds before failing —
worst case, hundreds of slow, doomed calls in flight during an outage
instead of failing fast.

Standard 3-state design (closed → open → half-open):
  closed:    normal operation. Failures are counted; N consecutive
             failures (llm_circuit_breaker_failure_threshold) opens it.
  open:      calls are refused immediately (CircuitBreakerOpenError, no
             network call at all) until the cooldown
             (llm_circuit_breaker_cooldown_seconds) elapses.
  half-open: exactly one trial call is allowed through to test recovery.
             Success closes the breaker (failure count resets); failure
             reopens it immediately (does not wait for N more failures).

One shared breaker instance per provider (get_anthropic_breaker(),
get_groq_breaker()) — module-level singletons, not per-call-site, since
the point is protecting the shared upstream dependency: if base_graph.py's
calls start failing, chat_agent.py's calls (hitting the same Anthropic
API) must see the same open breaker, not track independent state.
Thread-safe (a Lock guards state transitions) since many worker threads
call concurrently — same pattern as this codebase's own LessonStore
(app/agents/base_graph.py).
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CLOSED = "closed"
_OPEN = "open"
_HALF_OPEN = "half_open"


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a call is refused because the breaker is open."""


class CircuitBreaker:
    def __init__(
        self, name: str, failure_threshold: int, cooldown_seconds: float
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = Lock()
        self._state = _CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0

    def _ready_to_probe(self) -> bool:
        return (time.monotonic() - self._opened_at) >= self.cooldown_seconds

    def _open(self) -> None:
        self._state = _OPEN
        self._opened_at = time.monotonic()
        logger.warning(
            "Circuit breaker '%s' OPEN after %d consecutive failures — "
            "refusing calls for %.0fs",
            self.name,
            self._consecutive_failures,
            self.cooldown_seconds,
        )

    def allow(self) -> bool:
        """Returns True if a call may proceed right now. A caller that
        gets True back MUST call record_success() or record_failure()
        exactly once afterward — this is what lets a caller whose call
        shape doesn't fit a single wrapped callable (chat_agent.py's async
        streaming `async with client.messages.stream(...)` block) use the
        breaker directly instead of through call()/acall()."""
        with self._lock:
            if self._state == _OPEN:
                if self._ready_to_probe():
                    self._state = _HALF_OPEN
                    logger.info(
                        "Circuit breaker '%s' HALF_OPEN — probing with one trial call",
                        self.name,
                    )
                    return True
                return False
            if self._state == _HALF_OPEN:
                # A probe is already in flight on another thread/task;
                # refuse rather than letting every concurrent caller re-probe.
                return False
            return True

    def open_error_message(self) -> str:
        with self._lock:
            remaining = max(
                0.0, self.cooldown_seconds - (time.monotonic() - self._opened_at)
            )
        return (
            f"Circuit breaker '{self.name}' is open — refusing call "
            f"({remaining:.0f}s remaining before retry)"
        )

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._state = _CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if (
                self._state == _HALF_OPEN
                or self._consecutive_failures >= self.failure_threshold
            ):
                self._open()

    def call(self, fn: Callable[[], T]) -> T:
        """Runs fn() if the breaker allows it, else raises
        CircuitBreakerOpenError without calling fn() at all."""
        if not self.allow():
            raise CircuitBreakerOpenError(self.open_error_message())

        try:
            result = fn()
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result

    def reset(self) -> None:
        """Forces the breaker back to closed with a zeroed failure count.
        Test-only escape hatch — production code should never need this,
        since success already resets it via call()."""
        with self._lock:
            self._state = _CLOSED
            self._consecutive_failures = 0
            self._opened_at = 0.0


_anthropic_breaker: CircuitBreaker | None = None
_groq_breaker: CircuitBreaker | None = None
_breaker_lock = Lock()


def get_anthropic_breaker() -> CircuitBreaker:
    global _anthropic_breaker
    with _breaker_lock:
        if _anthropic_breaker is None:
            from app.config import get_settings

            settings = get_settings()
            _anthropic_breaker = CircuitBreaker(
                name="anthropic",
                failure_threshold=settings.llm_circuit_breaker_failure_threshold,
                cooldown_seconds=settings.llm_circuit_breaker_cooldown_seconds,
            )
        return _anthropic_breaker


def get_groq_breaker() -> CircuitBreaker:
    global _groq_breaker
    with _breaker_lock:
        if _groq_breaker is None:
            from app.config import get_settings

            settings = get_settings()
            _groq_breaker = CircuitBreaker(
                name="groq",
                failure_threshold=settings.llm_circuit_breaker_failure_threshold,
                cooldown_seconds=settings.llm_circuit_breaker_cooldown_seconds,
            )
        return _groq_breaker
