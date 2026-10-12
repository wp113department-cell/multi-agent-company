"""G9 (2026-10-12): every model the fleet uses has its real published price
(cache rates included), and an opt-in fallback chain keeps agents working
when a model is retired or overloaded.

Before: Sonnet-tier work was priced at $3/$15 per million tokens although
Claude Sonnet 5's standard price is $2/$10 (every Sonnet estimate 50% high),
and cache reads were assumed to cost 0.1x input on every model. No AI runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from app.config import get_settings
from app.fleet.model_pricing import cost_usd, price_for
from app.fleet.spend_guard import cost_of

MILLION = 1_000_000


def _usage(**kw: int) -> Any:
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    return SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize(
    ("model", "inp", "out", "read"),
    [
        ("claude-sonnet-5", 2, 10, 0.20),
        ("claude-haiku-4-5-20251001", 1, 5, 0.10),
        ("claude-opus-4-8", 5, 25, 0.50),
        ("claude-opus-5-5", 4, 20, 0.20),
        ("claude-sonnet-4-6", 3, 15, 0.30),
    ],
)
def test_published_prices(model: str, inp: float, out: float, read: float) -> None:
    p = price_for(model)
    assert p is not None
    assert (p.input, p.output, p.cache_read) == (inp, out, read)
    assert p.cache_write_5m == pytest.approx(inp * 1.25)
    assert p.cache_write_1h == pytest.approx(inp * 2)


def test_sonnet_work_is_charged_at_the_real_price() -> None:
    usage = _usage(input_tokens=MILLION, output_tokens=MILLION)
    assert cost_of("claude-sonnet-5", usage) == pytest.approx(12.0)  # was 18.0


def test_cache_reads_and_one_hour_writes_use_their_own_rates() -> None:
    reads = _usage(cache_read_input_tokens=MILLION)
    assert cost_usd("claude-opus-5-5", reads) == pytest.approx(0.20)  # 0.05x, not 0.1x
    split = _usage(cache_creation_input_tokens=MILLION)
    split.cache_creation = SimpleNamespace(
        ephemeral_1h_input_tokens=MILLION // 2, ephemeral_5m_input_tokens=MILLION // 2
    )
    assert cost_usd("claude-sonnet-5", split) == pytest.approx(0.5 * 4 + 0.5 * 2.5)


def test_an_unlisted_model_still_falls_back_to_its_tier_rate() -> None:
    usage = _usage(input_tokens=MILLION)
    s = get_settings()
    assert price_for("some-future-model") is None
    assert cost_of("some-future-model", usage) == pytest.approx(
        MILLION * s.cost_per_input_token
    )


def test_every_model_the_fleet_uses_has_a_price() -> None:
    table = json.loads(
        (
            Path(__file__).resolve().parents[1] / "app/fleet/agent_models.json"
        ).read_text()
    )
    models = {get_settings().model_coder, get_settings().model_planner}
    models.add(get_settings().model_router)

    def collect(obj: Any) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("model"), str):
                models.add(obj["model"])
            for value in obj.values():
                collect(value)
        elif isinstance(obj, list):
            for value in obj:
                collect(value)

    collect(table)
    missing = sorted(m for m in models if m.startswith("claude") and not price_for(m))
    assert not missing, f"add prices to app/fleet/model_pricing.py: {missing}"


def test_the_sonnet_tier_default_matches_the_table() -> None:
    from app.config import Settings

    fields = Settings.model_fields
    sonnet = price_for("claude-sonnet-5")
    assert sonnet is not None
    assert fields["cost_per_input_token"].default == pytest.approx(
        sonnet.input / MILLION
    )
    assert fields["cost_per_output_token"].default == pytest.approx(
        sonnet.output / MILLION
    )


# -- opt-in fallback chain -------------------------------------------------------------


def _error(cls: type[Exception], status: int) -> Exception:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("model problem", response=httpx.Response(status, request=req), body=None)  # type: ignore[call-arg]


@pytest.fixture
def fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        get_settings(),
        "model_fallbacks",
        {"claude-sonnet-5": "claude-sonnet-5-5", "claude-opus-4-8": "claude-opus-5"},
    )


def test_a_retired_model_falls_back_once(fallbacks: None) -> None:
    from app.agents.base_graph import _call_anthropic

    client = MagicMock()
    client.messages.create.side_effect = [_error(anthropic.NotFoundError, 404), "ok"]
    out = _call_anthropic(
        client,
        model="claude-sonnet-5",
        max_tokens=8192,
        messages=[],
        tool_choice={"type": "tool", "name": "submit_result"},
    )
    assert out == "ok"
    retried = client.messages.create.call_args_list[1].kwargs
    assert retried["model"] == "claude-sonnet-5-5"
    assert retried["tool_choice"] == {"type": "auto"}  # Sonnet 5.5 rejects forced


def test_thinking_is_adapted_and_overload_triggers_it(fallbacks: None) -> None:
    from app.agents.base_graph import _call_anthropic

    client = MagicMock()
    client.messages.create.side_effect = [
        _error(anthropic.InternalServerError, 529),
        "ok",
    ]
    _call_anthropic(
        client, model="claude-opus-4-8", max_tokens=8192, thinking={"type": "adaptive"}
    )
    retried = client.messages.create.call_args_list[1].kwargs
    assert retried["model"] == "claude-opus-5"
    assert retried["thinking"] == {"type": "adaptive"}


def test_no_fallback_unless_configured_or_for_other_errors(fallbacks: None) -> None:
    from app.agents.base_graph import _call_anthropic

    for model, err in (
        ("claude-haiku-4-5-20251001", _error(anthropic.NotFoundError, 404)),
        ("claude-sonnet-5", _error(anthropic.InternalServerError, 500)),
    ):
        client = MagicMock()
        client.messages.create.side_effect = [err, "ok"]
        with pytest.raises(type(err)):
            _call_anthropic(client, model=model, max_tokens=10, messages=[])
        assert client.messages.create.call_count == 1
