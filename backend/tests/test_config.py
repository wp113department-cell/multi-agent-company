"""Config loader tests — verify Pydantic Settings reads env vars correctly."""
import os
from unittest.mock import patch


def test_config_loads_required_vars():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
    }
    with patch.dict(os.environ, env, clear=False):
        # Reset singleton so fresh load picks up patched env
        import app.config as cfg_module
        cfg_module._settings = None
        from app.config import Settings
        s = Settings()
        assert s.database_url == env["DATABASE_URL"]
        assert s.anthropic_api_key == env["ANTHROPIC_API_KEY"]
        cfg_module._settings = None


def test_config_defaults():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
    }
    with patch.dict(os.environ, env, clear=False):
        import app.config as cfg_module
        cfg_module._settings = None
        from app.config import Settings
        s = Settings()
        assert s.pipeline_mode == "full"
        assert s.max_retries == 3
        assert s.model_router == "claude-haiku-4-5-20251001"
        assert s.voyage_api_key == ""
        cfg_module._settings = None


def test_config_model_tier_overridable():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "MODEL_PLANNER": "claude-opus-4-8",
    }
    with patch.dict(os.environ, env, clear=False):
        import app.config as cfg_module
        cfg_module._settings = None
        from app.config import Settings
        s = Settings()
        assert s.model_planner == "claude-opus-4-8"
        cfg_module._settings = None
