"""Central model router for all 68 Gridiron agents.

Loads agent_models.json at startup. route(agent_name) returns provider, model,
and token config. No model strings are hardcoded here — edit the JSON to change routing.

Usage:
    from app.fleet.model_router import get_model_router
    config = get_model_router().route("architect")
    # config.model  -> "claude-opus-4-20250514"
    # config.provider -> "anthropic"
    # config.max_tokens -> 8192
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteConfig:
    agent_name: str
    provider: str  # "anthropic" | "openai"
    model: str  # full model ID
    tier: str  # "opus" | "sonnet" | "haiku" | "gpt"
    max_tokens: int
    thinking_budget: int | None
    temperature: float

    def token_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for an Anthropic messages.create() call."""
        kw: dict[str, Any] = {
            "max_tokens": self.max_tokens,
        }
        if self.thinking_budget is not None:
            kw["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}
        return kw


# ---------------------------------------------------------------------------
# Tier configs — loaded from JSON _tiers block
# ---------------------------------------------------------------------------

_DEFAULT_TIERS: dict[str, dict[str, Any]] = {
    "opus": {"max_tokens": 8192, "thinking_budget": 2048, "temperature": 1.0},
    "sonnet": {"max_tokens": 4096, "thinking_budget": None, "temperature": 1.0},
    "haiku": {"max_tokens": 1024, "thinking_budget": None, "temperature": 0.5},
    "gpt": {"max_tokens": 4096, "thinking_budget": None, "temperature": 0.7},
}


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Thread-safe singleton. Loads agent_models.json once at startup."""

    def __init__(self, json_path: str | Path | None = None) -> None:
        self._lock = Lock()
        self._table: dict[str, dict[str, Any]] = {}
        self._tiers: dict[str, dict[str, Any]] = {}
        self._default: dict[str, Any] = {}
        self._load(json_path)

    def _load(self, json_path: str | Path | None) -> None:
        if json_path is None:
            # Resolve relative to this file's location
            json_path = Path(__file__).parent / "agent_models.json"
        path = Path(json_path)
        if not path.exists():
            logger.warning(
                "agent_models.json not found at %s — using built-in defaults", path
            )
            self._tiers = _DEFAULT_TIERS
            self._default = {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "tier": "sonnet",
            }
            return
        try:
            data = json.loads(path.read_text())
            self._tiers = {k: v for k, v in data.get("_tiers", _DEFAULT_TIERS).items()}
            self._default = data.get(
                "DEFAULT",
                {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "tier": "sonnet",
                },
            )
            # Strip metadata keys (start with _ or "DEFAULT")
            self._table = {
                k: v
                for k, v in data.items()
                if not k.startswith("_") and k != "DEFAULT"
            }
            logger.info(
                "ModelRouter loaded %d agent entries from %s", len(self._table), path
            )
        except Exception as exc:
            logger.error("Failed to load agent_models.json: %s", exc)
            self._tiers = _DEFAULT_TIERS
            self._default = {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "tier": "sonnet",
            }

    def reload(self, json_path: str | Path | None = None) -> None:
        """Hot-reload the routing table without restarting."""
        with self._lock:
            self._load(json_path)

    def route(self, agent_name: str) -> RouteConfig:
        """Return routing config for agent_name. Falls back to DEFAULT if not found."""
        entry = self._table.get(agent_name, self._default)
        tier = entry.get("tier", "sonnet")
        tier_cfg = self._tiers.get(tier, _DEFAULT_TIERS["sonnet"])
        return RouteConfig(
            agent_name=agent_name,
            provider=entry.get("provider", "anthropic"),
            model=entry.get("model", "claude-sonnet-4-20250514"),
            tier=tier,
            max_tokens=tier_cfg.get("max_tokens", 4096),
            thinking_budget=tier_cfg.get("thinking_budget"),
            temperature=tier_cfg.get("temperature", 1.0),
        )

    def model_for(self, agent_name: str) -> str:
        """Convenience shortcut — returns just the model string."""
        return self.route(agent_name).model

    def all_agents(self) -> list[str]:
        """Return all agent names in the routing table."""
        return list(self._table.keys())

    def agents_by_provider(self, provider: str) -> list[str]:
        return [
            name
            for name, entry in self._table.items()
            if entry.get("provider") == provider
        ]

    def agents_by_tier(self, tier: str) -> list[str]:
        return [
            name for name, entry in self._table.items() if entry.get("tier") == tier
        ]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_router: ModelRouter | None = None
_router_lock = Lock()


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                # Allow override via env var
                custom_path = os.environ.get("AGENT_MODELS_PATH")
                _router = ModelRouter(json_path=custom_path)
    return _router


def reset_model_router() -> None:
    """Test-only: reset the singleton."""
    global _router
    _router = None
