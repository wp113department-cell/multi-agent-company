"""Gap-closure Day 7 (answers.md Q21) — proves CREDENTIAL_ENCRYPTION_KEY is now
hard-required at startup when DEPLOYMENT_ENV=production, instead of only ever
logging a startup warning (app/security/credential_vault.py's plaintext
fallback, which stays intact and still applies outside production).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings

_DB_URL = "postgresql+asyncpg://user:pass@localhost:5432/testdb"


def test_deployment_env_defaults_to_development() -> None:
    f = Settings.model_fields["deployment_env"]
    assert f.default == "development"


def test_development_without_encryption_key_does_not_raise() -> None:
    s = Settings(
        database_url=_DB_URL, deployment_env="development", credential_encryption_key=""
    )
    assert s.credential_encryption_key == ""


def test_production_without_encryption_key_raises() -> None:
    with pytest.raises(ValidationError, match="CREDENTIAL_ENCRYPTION_KEY must be set"):
        Settings(
            database_url=_DB_URL,
            deployment_env="production",
            credential_encryption_key="",
        )


def test_production_with_valid_encryption_key_does_not_raise() -> None:
    """Isolates the credential-encryption gate: a production config that also
    satisfies _require_secure_production_auth's other gates (JWT/RBAC/admin
    password — see test_production_secure_auth_gate.py for those in
    isolation) must not raise once CREDENTIAL_ENCRYPTION_KEY is valid."""
    key = Fernet.generate_key().decode()
    s = Settings(
        database_url=_DB_URL,
        deployment_env="production",
        credential_encryption_key=key,
        jwt_auth_enabled=True,
        jwt_secret_key="a" * 32,
        rbac_enabled=True,
        allow_legacy_role_header=False,
        default_admin_password="a-genuinely-non-default-password",
        worktrees_dir="/var/lib/gridiron/worktrees",
        repos_dir="/var/lib/gridiron/repos",
        bg_process_registry_path="/var/lib/gridiron/bg-processes.json",
    )
    assert s.deployment_env == "production"
    assert s.credential_encryption_key == key


def test_staging_without_encryption_key_does_not_raise() -> None:
    """Only the exact "production" profile hard-fails — staging/development
    keep the pre-Day-7 optional-with-warning behavior."""
    s = Settings(
        database_url=_DB_URL, deployment_env="staging", credential_encryption_key=""
    )
    assert s.credential_encryption_key == ""
