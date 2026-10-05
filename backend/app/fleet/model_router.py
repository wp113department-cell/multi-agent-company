"""Central model router for every Gridiron agent (85 registered as of 2026-10-05).

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

import re

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


# Models that still take the fixed-budget form of extended thinking. Everything
# newer (Opus 4.7/4.8/5, Sonnet 5, Fable, ...) REMOVED `budget_tokens` and answers
# `thinking: {type: "enabled", ...}` with a 400 — found by a real end-to-end
# pipeline run: the Architect/Decomposer/Planner agents (opus-4-8) failed on
# their very first call, blocking every task at planning. Older models need
# the budget form; unknown/newer IDs default to the adaptive form.
_LEGACY_THINKING_MODEL_RE = re.compile(
    r"^claude-(?:3|haiku-4-5|sonnet-4-5|opus-4-5|opus-4-1|sonnet-4(?:-\d{8})?$|opus-4(?:-\d{8})?$)"
)


def thinking_param_for(model: str, budget_tokens: int) -> dict[str, Any]:
    """The `thinking` request parameter that is valid for `model`."""
    if _LEGACY_THINKING_MODEL_RE.match(model or ""):
        return {"type": "enabled", "budget_tokens": budget_tokens}
    return {"type": "adaptive"}


@dataclass(frozen=True)
class RouteConfig:
    agent_name: str
    provider: str  # "anthropic" | "openai"
    model: str  # full model ID
    tier: str  # "opus" | "sonnet" | "haiku" | "gpt"
    max_tokens: int
    thinking_budget: int | None
    temperature: float
    context_window: int  # real model input-token ceiling — see TIER_CONTEXT_WINDOWS

    def token_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for an Anthropic messages.create() call."""
        kw: dict[str, Any] = {
            "max_tokens": self.max_tokens,
        }
        if self.thinking_budget is not None:
            kw["thinking"] = thinking_param_for(self.model, self.thinking_budget)
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

# Gap-closure Stage 1.5 (answers.md) — model→context-window table, sourced
# (not guessed) via live web search on 2026-07-31, not training-data
# recall: the 1M-token context window is General Availability (default, no
# beta header) for current-generation Opus/Sonnet as of 2026-03-13
# (Anthropic API release notes); Haiku 4.5 is confirmed at 200K (matches
# this fleet's pinned "claude-haiku-4-5-20251001"). The "gpt" tier's real
# models (Groq's qwen/qwen3-32b, llama-3.1-8b-instant — see
# Settings.groq_model_*) are confirmed at 128K via Groq's own model docs;
# note both were deprecated by Groq on 2026-06-17 — a real, separate,
# out-of-scope-for-this-item gap flagged in answers.md, not fixed here.
# This is a ceiling for validation/percentage-of-real-limit purposes; the
# actual day-to-day trim/condense threshold remains context_token_budget
# (Settings), which is deliberately far below any of these numbers already.
TIER_CONTEXT_WINDOWS: dict[str, int] = {
    "opus": 1_000_000,
    "sonnet": 1_000_000,
    "haiku": 200_000,
    "gpt": 128_000,
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
        # In-memory, per-agent-name override — checked before _table in
        # route(). Not persisted to agent_models.json. Exists because
        # barot_agent's temporary_agent instances get a fresh, unique
        # agent_name per spawn (never present in the static JSON file), so
        # without this, route() would silently fall back to DEFAULT and
        # discard whatever model the caller (run_agent_graph's own model=
        # kwarg) actually asked for — see run_agent_graph's own comment
        # that "ModelRouter wins over passed-in model". Set at spawn time,
        # cleared at teardown; guarded by the same lock as _table.
        self._overrides: dict[str, dict[str, Any]] = {}
        self._load(json_path)

    def set_override(
        self,
        agent_name: str,
        *,
        model: str,
        provider: str = "anthropic",
        tier: str = "sonnet",
    ) -> None:
        """Register a per-agent-name model override that route() consults
        before the static table. Intended for runtime-registered agents
        (e.g. barot_agent's temporary_agent instances) whose name will never
        appear in agent_models.json."""
        with self._lock:
            self._overrides[agent_name] = {
                "model": model,
                "provider": provider,
                "tier": tier,
            }

    def clear_override(self, agent_name: str) -> None:
        """Remove a previously-set override. No-op if absent — safe to call
        unconditionally during teardown."""
        with self._lock:
            self._overrides.pop(agent_name, None)

    def _fallback_default(self) -> dict[str, Any]:
        """Last-resort default when agent_models.json is missing/unreadable —
        sourced from config.py's model_coder (the same single source of
        truth every other model reference in this codebase uses), not a
        second, independently-hardcoded literal that can silently drift out
        of sync with it (gap-closure 2026-07-23: this file's own fallback
        had drifted to a different, stale model string than config.py's
        real default, a direct violation of CLAUDE.md's zero-hardcoding
        rule — "Model names live in config... so we can swap models without
        code changes")."""
        from app.config import get_settings

        return {
            "provider": "anthropic",
            "model": get_settings().model_coder,
            "tier": "sonnet",
        }

    def _load(self, json_path: str | Path | None) -> None:
        if json_path is None:
            # Resolve relative to this file's location
            json_path = Path(__file__).parent / "agent_models.json"
        path = Path(json_path)
        self._path = path
        try:
            self._mtime: float | None = path.stat().st_mtime
        except OSError:
            self._mtime = None
        if not path.exists():
            logger.warning(
                "agent_models.json not found at %s — using built-in defaults", path
            )
            self._tiers = _DEFAULT_TIERS
            self._default = self._fallback_default()
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._tiers = {k: v for k, v in data.get("_tiers", _DEFAULT_TIERS).items()}
            self._default = data.get("DEFAULT", self._fallback_default())
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
            self._default = self._fallback_default()

    def reload(self, json_path: str | Path | None = None) -> None:
        """Hot-reload the routing table without restarting."""
        with self._lock:
            self._load(json_path)

    def _reload_if_changed(self) -> None:
        """Production audit 2026-09-29: reload() had no caller, so edits to
        agent_models.json (whose own header says "edit this file to change
        models") only took effect after a restart. Re-read when the file's
        mtime changes — one stat() per route() call. A file caught mid-edit
        (invalid JSON) keeps the previous table instead of falling back to
        built-in defaults for every agent."""
        path = getattr(self, "_path", None)
        if path is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime == self._mtime:
            return
        with self._lock:
            if mtime == self._mtime:
                return
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("agent_models.json must be a JSON object")
            except Exception as exc:
                logger.warning(
                    "agent_models.json changed but is invalid (%s) — keeping "
                    "the previous routing table",
                    exc,
                )
                self._mtime = mtime
                return
            self._load(path)
            logger.info("agent_models.json changed — routing table reloaded")

    def route(self, agent_name: str) -> RouteConfig:
        """Return routing config for agent_name. Checks the in-memory
        override table first (see set_override), then the static
        agent_models.json table, then falls back to DEFAULT."""
        self._reload_if_changed()
        entry = self._overrides.get(agent_name) or self._table.get(
            agent_name, self._default
        )
        tier = entry.get("tier", "sonnet")
        tier_cfg = self._tiers.get(tier, _DEFAULT_TIERS["sonnet"])
        return RouteConfig(
            agent_name=agent_name,
            provider=entry.get("provider", "anthropic"),
            model=entry.get("model") or self._fallback_default()["model"],
            tier=tier,
            max_tokens=tier_cfg.get("max_tokens", 4096),
            thinking_budget=tier_cfg.get("thinking_budget"),
            temperature=tier_cfg.get("temperature", 1.0),
            context_window=TIER_CONTEXT_WINDOWS.get(tier, 200_000),
        )

    def context_window_for(self, agent_name: str) -> int:
        """Convenience shortcut — returns just the real model context window."""
        return self.route(agent_name).context_window

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
