"""Config loader tests — verify Pydantic Settings reads env vars correctly."""

import os
from unittest.mock import MagicMock, patch

import pytest


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


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH11 §21 "Secret management" — optional AWS Secrets Manager
# overlay (app/security/secrets_manager.py + Settings._load_secrets_manager_
# overrides). Disabled by default: test_config_loads_required_vars and every
# other test in this file above already prove behavior is unchanged when
# SECRETS_MANAGER_ENABLED is unset. These prove the opt-in path itself.
# ---------------------------------------------------------------------------


def test_config_secrets_manager_disabled_by_default_is_a_no_op():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
    }
    with patch.dict(os.environ, env, clear=False):
        import app.config as cfg_module

        cfg_module._settings = None
        from app.config import Settings

        with patch("boto3.client") as mock_boto:
            s = Settings()
        mock_boto.assert_not_called()
        assert s.secrets_manager_enabled is False
        assert s.anthropic_api_key == "sk-ant-test-key"
        cfg_module._settings = None


def test_config_secrets_manager_fills_unset_fields_only():
    """A fetched value fills a field with no env var set, but never
    overrides one that IS explicitly set — explicit env always wins."""
    import json

    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-explicit-env-value",
        "SECRETS_MANAGER_ENABLED": "true",
        "SECRETS_MANAGER_SECRET_ID": "gridiron/test/secrets",
    }
    fake_secret = {
        "anthropic_api_key": "sk-ant-from-secrets-manager",  # must be ignored
        "openai_api_key": "sk-oai-from-secrets-manager",  # must be applied
    }
    with patch.dict(os.environ, env, clear=False):
        import app.config as cfg_module

        cfg_module._settings = None
        from app.config import Settings

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(fake_secret)
        }
        with patch("boto3.client", return_value=mock_client) as mock_boto:
            s = Settings()

        mock_boto.assert_called_once_with("secretsmanager", region_name=None)
        assert s.anthropic_api_key == "sk-ant-explicit-env-value"
        assert s.openai_api_key == "sk-oai-from-secrets-manager"
        cfg_module._settings = None


def test_config_secrets_manager_enabled_without_secret_id_fails_closed():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "SECRETS_MANAGER_ENABLED": "true",
    }
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("SECRETS_MANAGER_SECRET_ID", None)
        import app.config as cfg_module

        cfg_module._settings = None
        from app.config import Settings
        from app.security.secrets_manager import SecretsManagerError

        with pytest.raises(SecretsManagerError, match="SECRETS_MANAGER_SECRET_ID"):
            Settings()
        cfg_module._settings = None


def test_config_secrets_manager_fetch_failure_fails_closed_not_silent():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/testdb",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "SECRETS_MANAGER_ENABLED": "true",
        "SECRETS_MANAGER_SECRET_ID": "gridiron/test/secrets",
    }
    with patch.dict(os.environ, env, clear=False):
        import app.config as cfg_module

        cfg_module._settings = None
        from app.config import Settings
        from app.security.secrets_manager import SecretsManagerError

        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "GetSecretValue",
        )
        with patch("boto3.client", return_value=mock_client):
            with pytest.raises(SecretsManagerError, match="Failed to fetch secret"):
                Settings()
        cfg_module._settings = None
