"""Sol A24 (2026-10-12): the daily cap reserves each call's worst-case cost
before it is sent, so calls in flight see each other.

Before: the cap was checked before a call and the cost added after it, so
many calls started together all saw the same low total and all went
through. Real anthropic SDK classes with an in-memory transport: no
network, no key, no spend.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import anthropic
import httpx
import pytest

from app.config import get_settings
from app.fleet import spend_guard

USAGE = {"input_tokens": 1000, "output_tokens": 1000}
# claude-sonnet-5: $2 in / $10 out per million -> one real call costs $0.012
REAL_COST = (1000 * 2 + 1000 * 10) / 1_000_000


class _SlowModel:
    """Answers after a pause, so many calls are in flight at once."""

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.calls += 1
        time.sleep(0.3)
        if self.fail:
            return httpx.Response(500, json={"type": "error", "error": {}})
        model = json.loads(request.content)["model"]
        return httpx.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": USAGE,
            },
        )


@pytest.fixture()
def guard(monkeypatch: pytest.MonkeyPatch) -> Any:
    spend_guard.install()
    spend_guard.reset_local_for_tests()
    monkeypatch.setattr(get_settings(), "spend_guard_redis", False)
    yield spend_guard
    spend_guard.reset_local_for_tests()


def _call(model: _SlowModel, max_tokens: int = 1000) -> str:
    client = anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(model)),
    )
    try:
        client.messages.create(
            model="claude-sonnet-5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": "hi"}],
        )
        return "sent"
    except spend_guard.DailyBudgetExceeded:
        return "refused"
    except anthropic.APIStatusError:
        return "failed"


def test_calls_in_flight_count_against_the_cap(
    guard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # worst case per call is about $0.010 (1000 output tokens at $10/M plus a
    # little input), so a $0.05 cap admits about 5 of 20 simultaneous calls
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 0.05)
    model = _SlowModel()
    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(_call(model))) for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sent = results.count("sent")
    assert model.calls == sent
    assert 1 <= sent <= 6, results  # before: all 20 went through
    # after settling, the total is what the admitted calls really cost
    assert guard.spent_today() == pytest.approx(sent * REAL_COST)


def test_a_failed_call_releases_its_reservation(
    guard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 1.0)
    assert _call(_SlowModel(fail=True)) == "failed"
    assert guard.spent_today() == pytest.approx(0.0)


def test_one_call_bigger_than_a_small_cap_can_still_run_once(
    guard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the most the cap is exceeded by is one call's worst case — it never
    # locks up because a single call's worst case is larger than the cap
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 0.001)
    assert _call(_SlowModel(), max_tokens=20_000) == "sent"
    assert _call(_SlowModel()) == "refused"


def test_without_the_shared_ledger_calls_can_be_refused(
    guard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 1.0)
    monkeypatch.setattr(get_settings(), "spend_guard_require_redis", True)
    assert _call(_SlowModel()) == "refused"  # spend_guard_redis is off here
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 0.0)
    assert _call(_SlowModel()) == "sent"  # no cap, nothing to protect


def test_the_estimate_uses_the_models_price() -> None:
    small = spend_guard.estimate_worst_case(
        "claude-haiku-4-5-20251001", {"max_tokens": 1000, "messages": []}
    )
    big = spend_guard.estimate_worst_case(
        "claude-opus-4-8", {"max_tokens": 1000, "messages": []}
    )
    assert big == pytest.approx(5 * small, rel=0.05)
