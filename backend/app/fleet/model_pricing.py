"""Per-model prices, including prompt-cache rates (G9, 2026-10-12).

Spend tracking used one input/output rate per tier and fixed cache
multipliers (writes 1.25x, reads 0.1x input). Two things were wrong: the
Sonnet tier was still priced at $3/$15 per million tokens, while Anthropic
made Claude Sonnet 5's $2/$10 the standard price (the increase planned for
2026-09-01 was cancelled); and cache reads are not 0.1x on every model
(Claude Opus 5.5 reads cost 0.05x). Prices below are USD per million tokens,
copied from https://platform.claude.com/docs/en/about-claude/pricing on
2026-10-12. A model not listed here falls back to the tier rates in
Settings (cost_per_input_token*).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

VERIFIED = "2026-10-12"
SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"


@dataclass(frozen=True)
class ModelPrice:
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


# Most specific first; matched against the model id (dated ids included).
_PRICES: tuple[tuple[re.Pattern[str], ModelPrice], ...] = tuple(
    (re.compile(pattern), ModelPrice(*rates))
    for pattern, rates in (
        (r"^claude-(fable|mythos)-5-1", (10, 12.5, 20, 0.25, 50)),
        (r"^claude-(fable|mythos)-5", (10, 12.5, 20, 1, 50)),
        (r"^claude-opus-5-5", (4, 5, 8, 0.20, 20)),
        (r"^claude-opus-(5|4-[5-8])", (5, 6.25, 10, 0.50, 25)),
        (r"^claude-opus-4", (15, 18.75, 30, 1.50, 75)),  # Opus 4 / 4.1
        (r"^claude-sonnet-5-5", (2, 2.5, 4, 0.10, 10)),
        (r"^claude-sonnet-5", (2, 2.5, 4, 0.20, 10)),
        (r"^claude-sonnet-4", (3, 3.75, 6, 0.30, 15)),  # 4, 4.5, 4.6
        (r"^claude-haiku-5-5", (0.10, 0.125, 0.20, 0.01, 0.50)),  # prompts <=100K
        (r"^claude-haiku-4-5", (1, 1.25, 2, 0.10, 5)),
        (r"^claude-3-5-haiku", (0.80, 1, 1.6, 0.08, 4)),
    )
)


def price_for(model: str) -> ModelPrice | None:
    name = (model or "").lower()
    for pattern, price in _PRICES:
        if pattern.match(name):
            return price
    return None


def _n(obj: Any, attr: str) -> int:
    value = getattr(obj, attr, 0) if not isinstance(obj, dict) else obj.get(attr, 0)
    return value if isinstance(value, int) else 0


def cost_usd(model: str, usage: Any) -> float | None:
    """USD for one response's usage, or None when the model is not listed.

    Cache writes are split by lifetime when the API reports it
    (usage.cache_creation.ephemeral_1h_input_tokens); otherwise they are
    priced as 5-minute writes, which is what this code requests.
    """
    price = price_for(model)
    if price is None:
        return None
    written = _n(usage, "cache_creation_input_tokens")
    split = getattr(usage, "cache_creation", None)
    written_1h = _n(split, "ephemeral_1h_input_tokens") if split is not None else 0
    written_5m = max(0, written - written_1h)
    per_million = (
        _n(usage, "input_tokens") * price.input
        + written_5m * price.cache_write_5m
        + written_1h * price.cache_write_1h
        + _n(usage, "cache_read_input_tokens") * price.cache_read
        + _n(usage, "output_tokens") * price.output
    )
    return per_million / 1_000_000
