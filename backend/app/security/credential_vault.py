"""Credential Vault — Day 17.

Global-scoped (this project has no "project" entity — see docs/DAY17_PLAN.md
for why the plan's per-project pseudocode was adapted). Wraps the one real
choke point for credential storage that already existed since Days 9/14
(app.db.repository.get_setting()/set_setting(), backed by the SystemSetting
table) with:
  1. Encryption at rest (encrypt_value()/decrypt_value(), Fernet, optional —
     falls back to plaintext with a one-time startup warning when
     CREDENTIAL_ENCRYPTION_KEY is unset, never a silently hardcoded key).
  2. An explicit SecretStr + expose_secrets serialization gate (matches
     open-hands's real Secrets model — Pydantic already masks SecretStr by
     default, this is a deliberate, auditable, defense-in-depth gate on top).
  3. Audit logging of every credential access (key name only, via the
     existing app.fleet.audit_log — Day 13 already established this as the
     mechanism for security-relevant events).

database_url is deliberately NOT a vault-manageable credential — see
docs/DAY17_PLAN.md's plan/reality correction #2 (CLAUDE.md's own Permanent
Safety Rule: "No agent ever gets deploy credentials").
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, SecretStr, SerializationInfo, field_serializer

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:v1:"
_CUSTOM_SECRET_PREFIX = "custom_secret:"

_warned_plaintext = False


# ---------------------------------------------------------------------------
# Encryption primitives — used by both this module and app.db.repository's
# get_setting()/set_setting() (a local import there, matching this codebase's
# established convention for cross-layer imports).
# ---------------------------------------------------------------------------


def _get_fernet() -> Any | None:
    """Returns a Fernet instance if CREDENTIAL_ENCRYPTION_KEY is configured,
    else None (logs a one-time warning). Never raises for a missing key —
    only for a key that's set but invalid (caught at Settings load time)."""
    global _warned_plaintext
    from app.config import get_settings

    key = get_settings().credential_encryption_key
    if not key:
        if not _warned_plaintext:
            logger.warning(
                "CREDENTIAL_ENCRYPTION_KEY is not set — SystemSetting-backed "
                "credentials (API keys, tokens, custom secrets) are stored in "
                "plaintext. Set CREDENTIAL_ENCRYPTION_KEY in production."
            )
            _warned_plaintext = True
        return None

    from cryptography.fernet import Fernet

    return Fernet(key.encode())


def encrypt_value(value: str) -> str:
    """Encrypt value if a key is configured, else return it unchanged
    (plaintext — the pre-Day-17 status quo). Never encrypts an empty string
    (the established "delete" sentinel for SystemSetting rows)."""
    if not value:
        return value
    fernet = _get_fernet()
    if fernet is None:
        return value
    token: str = fernet.encrypt(value.encode()).decode()
    return _ENC_PREFIX + token


def decrypt_value(value: str) -> str:
    """Decrypt a value written by encrypt_value(). Legacy plaintext rows
    (written before encryption was configured, or whenever it's off) pass
    through unchanged — no prefix, no-op."""
    if not value.startswith(_ENC_PREFIX):
        return value
    fernet = _get_fernet()
    if fernet is None:
        raise RuntimeError(
            "Cannot decrypt a credential — this value was encrypted but "
            "CREDENTIAL_ENCRYPTION_KEY is not currently set."
        )
    token = value[len(_ENC_PREFIX) :]
    decrypted: str = fernet.decrypt(token.encode()).decode()
    return decrypted


# ---------------------------------------------------------------------------
# ProjectCredentials — SecretStr model with an explicit expose_secrets gate
# ---------------------------------------------------------------------------


class ProjectCredentials(BaseModel):
    """Frozen — SecretStr fields never print in logs or repr. Serialized
    without real values unless the caller explicitly opts in via
    model_dump(context={"expose_secrets": True})."""

    model_config = {"frozen": True}

    github_token: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    custom_secrets: dict[str, SecretStr] = {}

    @field_serializer("github_token", "anthropic_api_key", when_used="always")
    def _serialize_secret(
        self, value: SecretStr | None, info: SerializationInfo
    ) -> str | None:
        if value is None:
            return None
        expose = bool(info.context and info.context.get("expose_secrets"))
        return value.get_secret_value() if expose else "**********"

    @field_serializer("custom_secrets", when_used="always")
    def _serialize_custom_secrets(
        self, value: dict[str, SecretStr], info: SerializationInfo
    ) -> dict[str, str]:
        expose = bool(info.context and info.context.get("expose_secrets"))
        return {
            k: (v.get_secret_value() if expose else "**********")
            for k, v in value.items()
        }

    def get_env_vars(self) -> dict[str, str]:
        """The one place .get_secret_value() is called for env injection."""
        env: dict[str, str] = {}
        if self.github_token:
            env["GITHUB_TOKEN"] = self.github_token.get_secret_value()
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key.get_secret_value()
        for k, v in self.custom_secrets.items():
            env[k] = v.get_secret_value()
        return env


# ---------------------------------------------------------------------------
# CredentialVault — thin wrapper over get_setting()/set_setting()
# ---------------------------------------------------------------------------


class CredentialVault:
    """Global-scoped (see module docstring). Every load/store is audit-logged
    (key name only, never the value) via the existing app.fleet.audit_log."""

    async def load(self, db: Any) -> ProjectCredentials:
        from app.db.repository import get_setting

        github_token = await get_setting(db, "github_token")
        anthropic_api_key = await get_setting(db, "anthropic_api_key")
        custom_secrets = await self._load_custom_secrets(db)

        self._audit(
            "load", list(custom_secrets.keys()) + ["github_token", "anthropic_api_key"]
        )

        return ProjectCredentials(
            github_token=SecretStr(github_token) if github_token else None,
            anthropic_api_key=(
                SecretStr(anthropic_api_key) if anthropic_api_key else None
            ),
            custom_secrets={k: SecretStr(v) for k, v in custom_secrets.items()},
        )

    async def store(self, db: Any, creds: ProjectCredentials) -> None:
        from app.db.repository import set_setting

        if creds.github_token is not None:
            await set_setting(db, "github_token", creds.github_token.get_secret_value())
        if creds.anthropic_api_key is not None:
            await set_setting(
                db, "anthropic_api_key", creds.anthropic_api_key.get_secret_value()
            )
        for name, secret in creds.custom_secrets.items():
            await set_setting(
                db, _CUSTOM_SECRET_PREFIX + name, secret.get_secret_value()
            )

        self._audit(
            "store",
            [k for k in ("github_token", "anthropic_api_key") if getattr(creds, k)]
            + list(creds.custom_secrets.keys()),
        )

    async def inject_into_env(self, db: Any) -> dict[str, str]:
        creds = await self.load(db)
        return creds.get_env_vars()

    async def _load_custom_secrets(self, db: Any) -> dict[str, str]:
        from app.db.repository import get_setting, list_setting_keys

        names = await list_setting_keys(db, _CUSTOM_SECRET_PREFIX)
        result: dict[str, str] = {}
        for full_key in names:
            value = await get_setting(db, full_key)
            if value:
                result[full_key[len(_CUSTOM_SECRET_PREFIX) :]] = value
        return result

    def _audit(self, action: str, key_names: list[str]) -> None:
        try:
            from app.fleet.audit_log import audit

            audit(
                action_type=f"credential_{action}",
                agent_name="credential_vault",
                description=f"Credential {action} — keys: {', '.join(sorted(set(key_names))) or '(none)'}",
                outcome="success",
            )
        except Exception:
            logger.debug("audit log unavailable for credential_%s (non-fatal)", action)


_vault = CredentialVault()


def get_credential_vault() -> CredentialVault:
    return _vault
