"""Tests for the central ModelRouter (Day 5A)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.fleet.model_router import (
    ModelRouter,
    RouteConfig,
    get_model_router,
    reset_model_router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset global router singleton between tests."""
    reset_model_router()
    yield
    reset_model_router()


def _make_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# RouteConfig
# ---------------------------------------------------------------------------


class TestRouteConfig:
    def test_token_kwargs_no_thinking(self):
        rc = RouteConfig(
            agent_name="coder",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            tier="sonnet",
            max_tokens=4096,
            thinking_budget=None,
            temperature=1.0,
        )
        kw = rc.token_kwargs()
        assert kw["max_tokens"] == 4096
        assert "thinking" not in kw

    def test_token_kwargs_with_thinking(self):
        rc = RouteConfig(
            agent_name="architect",
            provider="anthropic",
            model="claude-opus-4-20250514",
            tier="opus",
            max_tokens=8192,
            thinking_budget=2048,
            temperature=1.0,
        )
        kw = rc.token_kwargs()
        assert kw["max_tokens"] == 8192
        assert kw["thinking"] == {"type": "enabled", "budget_tokens": 2048}


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class TestModelRouter:
    def test_loads_production_json(self):
        router = ModelRouter()  # loads real agent_models.json
        agents = router.all_agents()
        # 68 from Days 0-8 + 5 Day 9 fleet-enhancement agents (agent_performance_reviewer,
        # agent_debugger, agent_advisor, knowledge_curator, quality_auditor)
        assert len(agents) == 73
        assert "architect" in agents
        assert "coder" in agents
        assert "agent_debugger" in agents

    def test_route_opus_tier(self):
        router = ModelRouter()
        cfg = router.route("architect")
        assert cfg.tier == "opus"
        assert cfg.max_tokens == 8192
        assert cfg.thinking_budget == 2048
        assert cfg.provider == "anthropic"
        assert "opus" in cfg.model

    def test_route_haiku_tier(self):
        router = ModelRouter()
        cfg = router.route("env_checker_agent")
        assert cfg.tier == "haiku"
        assert cfg.max_tokens == 1024
        assert cfg.thinking_budget is None

    def test_route_sonnet_tier(self):
        router = ModelRouter()
        cfg = router.route("coder")
        assert cfg.tier == "sonnet"
        assert cfg.max_tokens == 4096

    def test_fallback_to_default(self):
        router = ModelRouter()
        cfg = router.route("nonexistent_agent_xyz")
        assert cfg.tier == "sonnet"
        # Falls back to the real agent_models.json DEFAULT entry (a legit,
        # editable config value) — not asserting a specific literal here,
        # since that's the JSON's own data, not this test's concern.
        assert cfg.model
        assert cfg.provider == "anthropic"

    def test_model_for(self):
        router = ModelRouter()
        model = router.model_for("planner")
        assert "opus" in model

    def test_agents_by_tier(self):
        router = ModelRouter()
        opus_agents = router.agents_by_tier("opus")
        haiku_agents = router.agents_by_tier("haiku")
        assert "architect" in opus_agents
        assert "env_checker_agent" in haiku_agents
        assert len(opus_agents) >= 8
        assert len(haiku_agents) >= 2

    def test_agents_by_provider(self):
        router = ModelRouter()
        anthropic_agents = router.agents_by_provider("anthropic")
        assert len(anthropic_agents) >= 60

    def test_custom_json_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "custom.json"
            _make_json(
                p,
                {
                    "_tiers": {
                        "testier": {
                            "max_tokens": 999,
                            "thinking_budget": None,
                            "temperature": 0.5,
                        }
                    },
                    "DEFAULT": {"provider": "openai", "model": "gpt-4o", "tier": "gpt"},
                    "my_agent": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "tier": "testier",
                    },
                },
            )
            router = ModelRouter(json_path=str(p))
            assert "my_agent" in router.all_agents()
            cfg = router.route("my_agent")
            assert cfg.provider == "openai"
            assert cfg.max_tokens == 999

    def test_missing_json_uses_defaults(self):
        from app.config import get_settings

        router = ModelRouter(json_path="/nonexistent/path/models.json")
        # Should not raise; falls back to config.py's model_coder (gap-
        # closure 2026-07-23: this used to be a second, independently-
        # hardcoded literal that had already drifted from model_coder's
        # real value — now there is exactly one source of truth).
        cfg = router.route("architect")
        assert cfg.model == get_settings().model_coder

    def test_fallback_default_genuinely_reads_settings_model_coder(self):
        """Proves the wiring, not just a coincidental match — changes
        settings.model_coder and confirms the fallback actually follows it."""
        from unittest.mock import MagicMock, patch

        with patch("app.config.get_settings") as mock_get_settings:
            mock_get_settings.return_value = MagicMock(
                model_coder="test-marker-model-xyz"
            )
            router = ModelRouter(json_path="/nonexistent/path/models.json")
            cfg = router.route("architect")

        assert cfg.model == "test-marker-model-xyz"

    def test_hot_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "r.json"
            _make_json(
                p,
                {
                    "_tiers": {
                        "sonnet": {
                            "max_tokens": 4096,
                            "thinking_budget": None,
                            "temperature": 1.0,
                        }
                    },
                    "DEFAULT": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-20250514",
                        "tier": "sonnet",
                    },
                    "agent_a": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-20250514",
                        "tier": "sonnet",
                    },
                },
            )
            router = ModelRouter(json_path=str(p))
            assert "agent_a" in router.all_agents()

            # Update JSON and reload
            _make_json(
                p,
                {
                    "_tiers": {
                        "sonnet": {
                            "max_tokens": 4096,
                            "thinking_budget": None,
                            "temperature": 1.0,
                        }
                    },
                    "DEFAULT": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-20250514",
                        "tier": "sonnet",
                    },
                    "agent_a": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-20250514",
                        "tier": "sonnet",
                    },
                    "agent_b": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-20250514",
                        "tier": "sonnet",
                    },
                },
            )
            router.reload(json_path=str(p))
            assert "agent_b" in router.all_agents()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestGetModelRouter:
    def test_returns_same_instance(self):
        r1 = get_model_router()
        r2 = get_model_router()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        r1 = get_model_router()
        reset_model_router()
        r2 = get_model_router()
        assert r1 is not r2

    def test_env_var_override(self, monkeypatch, tmp_path):
        p = tmp_path / "override.json"
        _make_json(
            p,
            {
                "_tiers": {
                    "sonnet": {
                        "max_tokens": 1111,
                        "thinking_budget": None,
                        "temperature": 1.0,
                    }
                },
                "DEFAULT": {
                    "provider": "anthropic",
                    "model": "claude-override",
                    "tier": "sonnet",
                },
            },
        )
        monkeypatch.setenv("AGENT_MODELS_PATH", str(p))
        router = get_model_router()
        cfg = router.route("any_agent")
        assert cfg.model == "claude-override"
