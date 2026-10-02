"""Production audit 09 (2026-10-02): the daily LLM budget is a real hard stop.

Before: COST_BUDGET_DAILY_USD was checked only after an agent run had finished,
and per agent — so it never prevented a single paid call. Now every Anthropic
SDK call in the process is checked before it is sent and priced after it
returns (app/fleet/spend_guard.py).

These tests use the real anthropic SDK classes (the hook lives on them) with
an in-memory httpx transport: no network, no key, no spend.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import anthropic
import httpx
import pytest
from fastapi import HTTPException

from app.api.budget_gate import require_daily_budget
from app.config import get_settings
from app.fleet import spend_guard

_USAGE = {
    "input_tokens": 1000,
    "output_tokens": 200,
    "cache_creation_input_tokens": 400,
    "cache_read_input_tokens": 2000,
}


def _message_body(model: str) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": _USAGE,
    }


class _Counter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        model = json.loads(request.content)["model"]
        return httpx.Response(200, json=_message_body(model))


@pytest.fixture()
def guard(monkeypatch: pytest.MonkeyPatch) -> Any:
    spend_guard.install()
    spend_guard.reset_local_for_tests()
    monkeypatch.setattr(get_settings(), "spend_guard_redis", False)
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 1.0)
    yield spend_guard
    spend_guard.reset_local_for_tests()


def _client(counter: _Counter) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(counter)),
    )


def _expected_haiku_cost() -> float:
    s = get_settings()
    rin, rout = s.cost_per_input_token_haiku, s.cost_per_output_token_haiku
    return 1000 * rin + 400 * rin * 1.25 + 2000 * rin * 0.1 + 200 * rout


def test_every_sync_call_is_priced_with_cache_tokens(guard: Any) -> None:
    counter = _Counter()
    _client(counter).messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert counter.calls == 1
    assert guard.spent_today() == pytest.approx(_expected_haiku_cost())


def test_call_is_refused_before_sending_once_cap_is_reached(
    guard: Any,
) -> None:
    counter = _Counter()
    guard.record(1.0)  # today's spend == cap
    with pytest.raises(spend_guard.DailyBudgetExceeded):
        _client(counter).messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )
    assert counter.calls == 0, "a request was sent after the daily cap was reached"


def test_cap_is_fleet_wide_not_per_agent(guard: Any) -> None:
    # Spend recorded by any caller counts against every other caller.
    guard.record(0.6)
    guard.record(0.5)
    with pytest.raises(spend_guard.DailyBudgetExceeded):
        guard.check()


def test_zero_disables_the_cap(guard: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "cost_budget_daily_usd", 0.0)
    guard.record(100.0)
    guard.check()  # must not raise


def test_async_client_and_stream_are_guarded_too(guard: Any) -> None:
    counter = _Counter()

    async def _run() -> None:
        client = anthropic.AsyncAnthropic(
            api_key="test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(counter)),
        )
        await client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )
        guard.record(1.0)
        with pytest.raises(spend_guard.DailyBudgetExceeded):
            await client.messages.create(
                model="claude-sonnet-5-5",
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
        with pytest.raises(spend_guard.DailyBudgetExceeded):
            client.messages.stream(
                model="claude-sonnet-5-5",
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )

    asyncio.run(_run())
    assert counter.calls == 1
    s = get_settings()
    first = (
        1000 * s.cost_per_input_token
        + 400 * s.cost_per_input_token * 1.25
        + 2000 * s.cost_per_input_token * 0.1
        + 200 * s.cost_per_output_token
    )
    assert guard.spent_today() == pytest.approx(first + 1.0)


def test_api_refuses_new_work_with_429(guard: Any) -> None:
    guard.record(1.0)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_daily_budget())
    assert exc.value.status_code == 429
    assert "Daily LLM budget reached" in str(exc.value.detail)


def test_work_starting_endpoints_carry_the_gate() -> None:
    from app.api import approvals, chat, epics, specialized_agents, tasks

    gated = {
        (tasks, "/api/tasks/{task_id}/run"),
        (tasks, "/api/tasks/{task_id}/restart"),
        (tasks, "/api/tasks/{task_id}/approve"),
        (tasks, "/api/tasks/{task_id}/pipeline/approve"),
        (chat, "/sessions/{session_id}/messages"),
        (epics, "/{epic_id}/approve"),
        (epics, "/{epic_id}/approve-cost"),
        (approvals, "/{thread_id}/approve"),
        (specialized_agents, "/{agent_name}/run"),
        (specialized_agents, "/{agent_name}/run-sync"),
    }
    missing = []
    for module, suffix in gated:
        routes = [
            r
            for r in module.router.routes
            if getattr(r, "path", "").endswith(suffix) and "POST" in r.methods
        ]
        assert routes, f"route not found: {module.__name__} {suffix}"
        for r in routes:
            if not any(d.dependency is require_daily_budget for d in r.dependencies):
                missing.append((module.__name__, r.path))
    assert (
        not missing
    ), f"endpoints that start LLM work without the budget gate: {missing}"
