"""Gap-closure Day 22 (Stage 1.3, answers.md) — proves the new
CircuitBreaker (app/fleet/circuit_breaker.py) actually implements the
closed → open → half-open → closed/open state machine, not just that it
compiles. Direct unit tests against the class itself (no LLM calls, no
mocking of anthropic/groq — this file tests the breaker in isolation);
tests/test_gap22_circuit_breaker_wiring.py proves it's actually wired into
the real Anthropic/Groq call sites.
"""

from __future__ import annotations

import time

import pytest

from app.fleet.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


def _breaker(
    failure_threshold: int = 3, cooldown_seconds: float = 0.1
) -> CircuitBreaker:
    return CircuitBreaker(
        name="test",
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )


def test_closed_breaker_calls_fn_and_returns_its_result() -> None:
    cb = _breaker()
    result = cb.call(lambda: "ok")
    assert result == "ok"


def test_failures_below_threshold_stay_closed() -> None:
    cb = _breaker(failure_threshold=3)

    def fail() -> None:
        raise ValueError("boom")

    for _ in range(2):
        with pytest.raises(ValueError):
            cb.call(fail)

    # Still closed — a 3rd call attempt actually reaches fn (raises
    # ValueError, not CircuitBreakerOpenError).
    with pytest.raises(ValueError):
        cb.call(fail)


def test_reaching_threshold_opens_the_breaker_and_refuses_further_calls() -> None:
    cb = _breaker(failure_threshold=3, cooldown_seconds=60.0)
    calls = {"count": 0}

    def fail() -> None:
        calls["count"] += 1
        raise ValueError("boom")

    for _ in range(3):
        with pytest.raises(ValueError):
            cb.call(fail)
    assert calls["count"] == 3

    # Breaker is now open — fn must NOT be called at all.
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(fail)
    assert calls["count"] == 3, "fn must not run while the breaker is open"


def test_open_breaker_transitions_to_half_open_after_cooldown_and_probes() -> None:
    cb = _breaker(failure_threshold=1, cooldown_seconds=0.05)

    with pytest.raises(ValueError):
        cb.call(_raise_value_error)

    # Immediately after opening: still refused.
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "should not run")

    time.sleep(0.06)

    # Cooldown elapsed — the next call is the half-open probe and actually runs.
    result = cb.call(lambda: "recovered")
    assert result == "recovered"


def test_successful_half_open_probe_closes_the_breaker() -> None:
    cb = _breaker(failure_threshold=1, cooldown_seconds=0.05)
    with pytest.raises(ValueError):
        cb.call(_raise_value_error)
    time.sleep(0.06)

    cb.call(lambda: "recovered")

    # Closed again — many calls succeed with no CircuitBreakerOpenError.
    for _ in range(5):
        assert cb.call(lambda: "still fine") == "still fine"


def test_failed_half_open_probe_reopens_immediately_without_waiting_for_threshold() -> (
    None
):
    """A failed half-open probe is one call, not `failure_threshold` more
    calls, before the breaker refuses again — proves the recovery test
    itself doesn't get an inflated failure budget just because it's a
    probe."""
    cb = _breaker(failure_threshold=3, cooldown_seconds=0.05)

    for _ in range(3):
        with pytest.raises(ValueError):
            cb.call(_raise_value_error)
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "should not run")  # confirms it's actually open now

    time.sleep(0.06)
    with pytest.raises(ValueError):
        cb.call(_raise_value_error)  # this is the half-open probe; it fails

    # Immediately refused on the very next call — not after 3 more failures.
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "should not run")


def test_concurrent_calls_while_half_open_only_allow_one_probe() -> None:
    cb = _breaker(failure_threshold=1, cooldown_seconds=0.05)
    with pytest.raises(ValueError):
        cb.call(_raise_value_error)
    time.sleep(0.06)

    # Force the breaker into half-open without consuming the probe, by
    # calling the private state check directly is not test-appropriate;
    # instead simulate two threads racing by calling once (consumes the
    # transition+probe atomically) then confirming state resets to closed
    # on success — the "second concurrent caller refused" branch is
    # covered by reading the source's elif _HALF_OPEN branch directly
    # here via a slow fn and a second call issued before it returns.
    import threading

    results: list[str] = []
    barrier_entered = threading.Event()

    def slow_probe() -> str:
        barrier_entered.set()
        time.sleep(0.1)
        return "probe done"

    def run_probe() -> None:
        results.append(cb.call(slow_probe))

    t = threading.Thread(target=run_probe)
    t.start()
    barrier_entered.wait(timeout=1.0)
    # A second caller arriving while the probe is still in flight must be
    # refused, not allowed to also probe.
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "second probe")
    t.join(timeout=1.0)
    assert results == ["probe done"]


def test_reset_forces_closed_state() -> None:
    cb = _breaker(failure_threshold=1, cooldown_seconds=60.0)
    with pytest.raises(ValueError):
        cb.call(_raise_value_error)
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "refused")

    cb.reset()

    assert cb.call(lambda: "works again") == "works again"


def _raise_value_error() -> None:
    raise ValueError("boom")
