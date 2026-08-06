"""Covers Settings._require_secure_production_auth in isolation — the gate
that rejects a DEPLOYMENT_ENV=production config leaving control-plane access
open (JWT disabled, RBAC disabled, the legacy X-User-Role header allowed, or
a default/weak admin password). Previously untested: the only sibling test
file (test_credential_encryption_production_gate.py) exercised the
credential-encryption gate and didn't cover this one, even though both are
model_validator(mode="after") gates on the same Settings class guarding the
same "production" deployment_env.

Each raising test supplies every OTHER production gate as satisfied (a valid
Fernet credential_encryption_key, a >=32-char jwt_secret_key) so the single
gate under test is what actually fires — model_validator(mode="after")
methods run in declaration order and each one raises independently, so an
earlier gate's failure would otherwise mask the one being tested.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings

_DB_URL = "postgresql+asyncpg://user:pass@localhost:5432/testdb"


def _secure_production_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        database_url=_DB_URL,
        deployment_env="production",
        credential_encryption_key=Fernet.generate_key().decode(),
        jwt_auth_enabled=True,
        jwt_secret_key="a" * 32,
        rbac_enabled=True,
        allow_legacy_role_header=False,
        default_admin_password="a-genuinely-non-default-password",
        worktrees_dir="/var/lib/gridiron/worktrees",
        repos_dir="/var/lib/gridiron/repos",
        bg_process_registry_path="/var/lib/gridiron/bg-processes.json",
    )
    base.update(overrides)
    return base


def test_fully_secure_production_config_does_not_raise() -> None:
    s = Settings(**_secure_production_kwargs())  # type: ignore[arg-type]
    assert s.deployment_env == "production"


def test_jwt_disabled_in_production_raises() -> None:
    with pytest.raises(ValidationError, match="JWT_AUTH_ENABLED=true is required"):
        Settings(
            **_secure_production_kwargs(jwt_auth_enabled=False, jwt_secret_key="")  # type: ignore[arg-type]
        )


def test_rbac_disabled_in_production_raises() -> None:
    with pytest.raises(ValidationError, match="RBAC_ENABLED=true is required"):
        Settings(**_secure_production_kwargs(rbac_enabled=False))  # type: ignore[arg-type]


def test_legacy_role_header_allowed_in_production_raises() -> None:
    with pytest.raises(
        ValidationError, match="ALLOW_LEGACY_ROLE_HEADER=false is required"
    ):
        Settings(**_secure_production_kwargs(allow_legacy_role_header=True))  # type: ignore[arg-type]


def test_default_admin_password_in_production_raises() -> None:
    with pytest.raises(
        ValidationError, match="DEFAULT_ADMIN_PASSWORD must be a non-default value"
    ):
        Settings(**_secure_production_kwargs(default_admin_password="gridiron123"))  # type: ignore[arg-type]


def test_short_admin_password_in_production_raises() -> None:
    with pytest.raises(
        ValidationError, match="DEFAULT_ADMIN_PASSWORD must be a non-default value"
    ):
        Settings(**_secure_production_kwargs(default_admin_password="short1"))  # type: ignore[arg-type]


def test_gate_does_not_apply_outside_production() -> None:
    """development/staging keep the pre-existing permissive defaults —
    only the exact "production" profile hard-fails."""
    s = Settings(
        database_url=_DB_URL,
        deployment_env="staging",
        jwt_auth_enabled=False,
        rbac_enabled=False,
        allow_legacy_role_header=True,
        default_admin_password="gridiron123",
    )
    assert s.deployment_env == "staging"
