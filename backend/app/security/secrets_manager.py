"""Optional AWS Secrets Manager integration for loading Settings values.

AUDIT_Q_BATCH11 §21 "Secret management" — this project's secrets were
always plain env vars (via Pydantic BaseSettings), with real startup-crash
validation on critical ones (jwt_secret_key, default_admin_password) but no
secrets-manager integration at all; the only existing `boto3` usage
(app/artifacts/s3_store.py) is for S3 artifact bytes, unrelated to secret
loading. This module adds a real, working, opt-in overlay: when enabled,
Settings' own `_load_secrets_manager_overrides` model_validator (mode=
"before", see app/config.py) calls `fetch_secrets_manager_overrides()`
before field validation runs, and any value it returns for a field that
isn't already set via env var/.env file is used to fill that field.

Deliberately NOT wired to be mandatory anywhere (including
DEPLOYMENT_ENV=production) — unlike credential_encryption_key/jwt_secret_key,
requiring an external AWS resource to even start the app is a real
deployment-topology decision this audit finding didn't ask for and this
change must not make unilaterally for a project with no existing production
AWS deployment. Disabled by default (SECRETS_MANAGER_ENABLED=false), so
behavior is 100% unchanged unless an operator explicitly opts in.

Fails closed once opted in, matching this codebase's own established
sandbox.py precedent (SandboxUnavailableError): if SECRETS_MANAGER_ENABLED
is true and the fetch fails for any reason (missing IAM permissions, no
network, malformed secret JSON, bad secret ID), this raises
SecretsManagerError rather than silently booting with whatever env vars
happened to already be set — an operator who explicitly enabled this
integration would rather see a loud startup failure than a silently
incomplete/wrong configuration.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


class SecretsManagerError(RuntimeError):
    """Raised when SECRETS_MANAGER_ENABLED=true but the secret could not be
    fetched or parsed. Never caught to silently fall back to env-var-only
    config — that would defeat the purpose of opting in at all."""


def fetch_secrets_manager_overrides() -> dict[str, str]:
    """Reads SECRETS_MANAGER_ENABLED/SECRETS_MANAGER_SECRET_ID/
    SECRETS_MANAGER_REGION directly from os.environ (Settings itself doesn't
    exist yet at the point this runs, inside a `mode="before"`
    model_validator) and, if enabled, fetches + parses the secret.

    Returns {} when SECRETS_MANAGER_ENABLED is unset/false — the overlay is
    then a complete no-op, preserving pre-existing behavior exactly.

    The secret (AWS Secrets Manager "SecretString") must be a JSON object
    whose keys are Settings field names, case-insensitively (e.g.
    `{"anthropic_api_key": "sk-...", "jwt_secret_key": "..."}` or the
    equivalent upper-snake-case `ANTHROPIC_API_KEY` form) — both are
    normalized to lowercase here so either convention works.
    """
    if os.environ.get("SECRETS_MANAGER_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return {}

    secret_id = os.environ.get("SECRETS_MANAGER_SECRET_ID", "").strip()
    if not secret_id:
        raise SecretsManagerError(
            "SECRETS_MANAGER_ENABLED=true but SECRETS_MANAGER_SECRET_ID is not set."
        )
    region = os.environ.get("SECRETS_MANAGER_REGION", "").strip() or None

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except (
        ImportError
    ) as exc:  # pragma: no cover — boto3 is a real, already-installed dependency (s3_store.py)
        raise SecretsManagerError(
            "SECRETS_MANAGER_ENABLED=true but boto3 is not installed."
        ) from exc

    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_id)
    except (BotoCoreError, ClientError) as exc:
        raise SecretsManagerError(
            f"Failed to fetch secret {secret_id!r} from AWS Secrets Manager: {exc}"
        ) from exc

    raw = response.get("SecretString")
    if raw is None:
        raise SecretsManagerError(
            f"Secret {secret_id!r} has no SecretString (binary secrets are not "
            "supported — store a JSON object of field-name -> value pairs instead)."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecretsManagerError(
            f"Secret {secret_id!r}'s SecretString is not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise SecretsManagerError(
            f"Secret {secret_id!r}'s SecretString must be a JSON object, got "
            f"{type(parsed).__name__}."
        )

    overrides = {str(k).lower(): str(v) for k, v in parsed.items()}
    logger.info(
        "Loaded %d secret override(s) from AWS Secrets Manager (secret_id=%s)",
        len(overrides),
        secret_id,
    )
    return overrides
