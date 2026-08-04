"""Stage 3, Days 58-59 (PLAN.md) — "LLM-API outage/retry behavior under a
simulated real outage; circuit-breaker interaction from Stage 1.3."

answer2.md's Q66 flagged exponential backoff as **NOT VERIFIED this pass**
("prior session history claims it exists on the Anthropic client wrapper;
not re-derived fresh here"). This file re-derives it fresh, end to end,
against the real installed `anthropic` SDK (0.115.1) rather than assuming
prior-session history:

- `anthropic.Anthropic.__init__`'s own `max_retries: int = DEFAULT_MAX_RETRIES`
  (`anthropic._constants.DEFAULT_MAX_RETRIES == 2`) is real — the SDK retries
  automatically, nothing in this codebase built or needed to build its own
  retry loop around a single `messages.create()` call.
- `anthropic._base_client.BaseClient._calculate_retry_timeout` computes real
  exponential backoff (`INITIAL_RETRY_DELAY=0.5`, `MAX_RETRY_DELAY=8.0`,
  `sleep_seconds = min(0.5 * 2**nb_retries, 8.0)` with +/-25% jitter) and
  `_should_retry` retries on 408/409/429/5xx.
- `SyncAPIClient.request`'s retry loop calls `_sleep_for_retry`, which calls
  `time.sleep(timeout)` from `anthropic._base_client`'s own module-level
  `time` import — patched here (not skipped) so these tests stay fast while
  still exercising and asserting on the real computed backoff values.

What was NOT previously proven anywhere in this suite (`test_gap22_circuit_
breaker.py`/`test_gap22_circuit_breaker_wiring.py` both use a `MagicMock`
client whose `messages.create` raises a plain `Exception` directly — they
prove the `CircuitBreaker` class and its wiring, not its interaction with
the SDK's own real retry mechanics): whether `app/agents/base_graph.py::
_call_anthropic()`'s breaker-wrapped call sees the SDK's internal retries as
transparent (i.e. the breaker's failure counter advances once per fully-
exhausted `messages.create()` call, not once per individual HTTP attempt),
and that an open breaker genuinely stops all further network traffic during
an outage rather than merely raising after the SDK's own retries. Both are
proven here against a real `httpx.MockTransport` simulating a real outage —
not mocked at the `anthropic.Anthropic` class level.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import anthropic
import httpx
import pytest

from app.fleet.circuit_breaker import CircuitBreakerOpenError, get_anthropic_breaker

_MAX_RETRIES = anthropic._constants.DEFAULT_MAX_RETRIES  # 2 -> 3 attempts total
_SUCCESS_BODY = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-4-5-20251001",
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def _client_with_transport(handler: httpx.MockTransport) -> anthropic.Anthropic:
    """Mirrors app/agents/base_graph.py::_make_client()'s real construction
    (api_key + timeout), injecting a mock transport in place of the real
    network so no live API call is ever made."""
    return anthropic.Anthropic(
        api_key="sk-ant-test-key",
        timeout=5.0,
        http_client=httpx.Client(transport=handler),
    )


@pytest.fixture(autouse=True)
def _reset_breaker() -> Iterator[None]:
    breaker = get_anthropic_breaker()
    breaker.reset()
    yield
    breaker.reset()


def test_sdk_retries_with_real_exponential_backoff_before_succeeding() -> None:
    """A real outage that clears after 2 failed attempts: the SDK's own
    retry loop (not custom code in this repo) must retry with real
    exponential backoff and eventually return the successful response."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(
                500,
                json={
                    "type": "error",
                    "error": {
                        "type": "internal_server_error",
                        "message": "simulated outage",
                    },
                },
            )
        return httpx.Response(200, json=_SUCCESS_BODY)

    client = _client_with_transport(httpx.MockTransport(handler))

    sleep_calls: list[float] = []
    with patch("anthropic._base_client.time.sleep", side_effect=sleep_calls.append):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )

    assert attempts["n"] == 3  # 1 original + 2 retries, matching DEFAULT_MAX_RETRIES=2
    block = response.content[0]
    assert isinstance(block, anthropic.types.TextBlock)
    assert block.text == "ok"

    # Real exponential backoff, not a fixed/linear delay: nb_retries=0 -> ~0.5s
    # base, nb_retries=1 -> ~1.0s base, each +/-25% jitter per
    # _calculate_retry_timeout's own formula.
    assert len(sleep_calls) == 2
    assert 0.375 <= sleep_calls[0] <= 0.625
    assert 0.75 <= sleep_calls[1] <= 1.25
    assert (
        sleep_calls[1] > sleep_calls[0]
    )  # strictly increasing = exponential, not constant


def test_sdk_raises_after_exhausting_all_retries_on_persistent_outage() -> None:
    """A real outage that never clears: the SDK must give up after exactly
    max_retries+1 attempts and raise, not retry forever or silently succeed."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(
            503,
            json={
                "type": "error",
                "error": {
                    "type": "overloaded_error",
                    "message": "simulated persistent outage",
                },
            },
        )

    client = _client_with_transport(httpx.MockTransport(handler))

    with patch("anthropic._base_client.time.sleep"):
        with pytest.raises(anthropic.APIStatusError):
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )

    assert attempts["n"] == _MAX_RETRIES + 1


def test_circuit_breaker_counts_one_failure_per_call_not_per_http_attempt() -> None:
    """The real interaction Stage 1.3's circuit breaker was built for:
    app/agents/base_graph.py::_call_anthropic() wraps breaker.call() around
    a single client.messages.create() invocation. During a real outage, the
    SDK retries internally (3 HTTP attempts) before that single call raises
    -- so the breaker must open after `failure_threshold` *calls*
    (== failure_threshold * 3 real HTTP attempts), not after
    `failure_threshold` raw HTTP failures. And once open, it must refuse
    without making any further HTTP attempt at all -- the entire point of
    Day 22's original build (stop hammering a real outage)."""
    from app.agents.base_graph import _call_anthropic

    attempts = {"n": 0}

    def always_fails(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(
            500,
            json={
                "type": "error",
                "error": {
                    "type": "internal_server_error",
                    "message": "simulated persistent outage",
                },
            },
        )

    client = _client_with_transport(httpx.MockTransport(always_fails))
    breaker = get_anthropic_breaker()

    with patch("anthropic._base_client.time.sleep"):
        for call_n in range(1, breaker.failure_threshold + 1):
            with pytest.raises(anthropic.APIStatusError):
                _call_anthropic(client, model="x", max_tokens=1, messages=[])
            # Each failed _call_anthropic() call did exactly (max_retries+1)
            # real HTTP attempts internally -- proving the breaker's
            # per-call counting is transparent to the SDK's own retries,
            # not double-counting or under-counting them.
            assert attempts["n"] == call_n * (_MAX_RETRIES + 1)

        # Breaker is now open. The next call must be refused WITHOUT any
        # network attempt -- this is the real outage-mitigation property,
        # not just "eventually raises an error".
        attempts_before_open_call = attempts["n"]
        with pytest.raises(CircuitBreakerOpenError):
            _call_anthropic(client, model="x", max_tokens=1, messages=[])
        assert attempts["n"] == attempts_before_open_call  # zero new HTTP traffic
