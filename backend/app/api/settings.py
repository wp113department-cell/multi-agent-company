"""Settings API — runtime-configurable values (API keys, etc.)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.db.repository import (
    delete_setting,
    get_setting,
    list_setting_keys,
    set_setting,
)
from app.middleware.rbac import require_approver, require_authenticated

router = APIRouter(prefix="/api/settings", tags=["settings"])

_ANTHROPIC_KEY = "anthropic_api_key"
_OPENAI_KEY = "openai_api_key"
_GITHUB_TOKEN_KEY = "github_token"
_CUSTOM_SECRET_PREFIX = "custom_secret:"


class ApiKeyRequest(BaseModel):
    api_key: str


class VerifyKeyRequest(BaseModel):
    provider: str  # "anthropic" | "openai"
    api_key: str


def _mask(key: str) -> str:
    if len(key) > 12:
        return key[:8] + "..." + key[-4:]
    return "set" if key else ""


async def _code_sandbox_available() -> bool:
    import asyncio

    from app.policy.sandbox import _docker_available

    settings = get_settings()
    if not settings.bash_sandbox_enabled:
        return True  # code runs unsandboxed (operator opt-out): it does run
    if not await asyncio.to_thread(_docker_available):
        return False
    # in the Docker version the task folders must also be shareable with the
    # sandbox containers (app/policy/docker_host.py)
    from app.policy.docker_host import SharedFolderError, engine_path

    try:
        for folder in (settings.worktrees_dir, settings.allowed_workspace_parent):
            await asyncio.to_thread(engine_path, folder)
    except SharedFolderError:
        return False
    return True


@router.get("")
async def get_settings_view(
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Return current settings. API keys masked — shows only first 8 + last 4 chars."""
    settings = get_settings()

    db_anthropic = await get_setting(db, _ANTHROPIC_KEY)
    eff_anthropic = db_anthropic or settings.anthropic_api_key

    db_openai = await get_setting(db, _OPENAI_KEY)
    eff_openai = db_openai or settings.openai_api_key

    db_github = await get_setting(db, _GITHUB_TOKEN_KEY)
    eff_github = db_github or settings.github_token

    return {
        "anthropicKeySet": bool(eff_anthropic),
        "anthropicKeyMasked": _mask(eff_anthropic),
        "anthropicKeySource": (
            "database"
            if db_anthropic
            else ("env" if settings.anthropic_api_key else "none")
        ),
        "openaiKeySet": bool(eff_openai),
        "openaiKeyMasked": _mask(eff_openai),
        "openaiKeySource": (
            "database" if db_openai else ("env" if settings.openai_api_key else "none")
        ),
        "githubTokenSet": bool(eff_github),
        "githubTokenMasked": _mask(eff_github),
        "githubTokenSource": (
            "database" if db_github else ("env" if settings.github_token else "none")
        ),
        # Whether tasks can run code/tests in the job sandbox here (needs a
        # reachable Docker; the Docker-compose API container has none). The
        # task form warns under "Max" when it is False.
        "codeSandboxAvailable": await _code_sandbox_available(),
        "usingGroq": settings.use_groq,
        "modelPlanner": settings.model_planner,
        "modelCoder": settings.model_coder,
    }


# ---------------------------------------------------------------------------
# Anthropic key
# ---------------------------------------------------------------------------


@router.post("/api-key")
async def save_api_key(
    body: ApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Save or update the Anthropic API key in the database."""
    key = body.api_key.strip()
    if not key.startswith("sk-"):
        raise HTTPException(
            status_code=400, detail="Invalid Anthropic API key — must start with 'sk-'"
        )
    await set_setting(db, _ANTHROPIC_KEY, key)
    from app.agents.base import set_api_key_override

    set_api_key_override(key)
    return {"saved": True, "provider": "anthropic"}


@router.delete("/api-key")
async def delete_api_key(
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Remove the DB-stored Anthropic API key (falls back to env var)."""
    from app.agents.base import set_api_key_override

    await set_setting(db, _ANTHROPIC_KEY, "")
    set_api_key_override("")
    return {"deleted": True, "provider": "anthropic"}


# ---------------------------------------------------------------------------
# OpenAI key
# ---------------------------------------------------------------------------


@router.post("/openai-key")
async def save_openai_key(
    body: ApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Save or update the OpenAI API key in the database."""
    key = body.api_key.strip()
    if not key.startswith("sk-"):
        raise HTTPException(
            status_code=400, detail="Invalid OpenAI API key — must start with 'sk-'"
        )
    await set_setting(db, _OPENAI_KEY, key)
    return {"saved": True, "provider": "openai"}


@router.delete("/openai-key")
async def delete_openai_key(
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Remove the DB-stored OpenAI API key."""
    await set_setting(db, _OPENAI_KEY, "")
    return {"deleted": True, "provider": "openai"}


# ---------------------------------------------------------------------------
# GitHub token (Day 14 — Git Push Workflow). No credential vault exists yet
# (Day 17 doesn't either) — SystemSetting is already the real, established
# mechanism for this (same table backing the Anthropic/OpenAI keys above).
# ---------------------------------------------------------------------------


@router.post("/github-token")
async def save_github_token(
    body: ApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Save or update the GitHub PAT in the database."""
    token = body.api_key.strip()
    if len(token) < 10:
        raise HTTPException(
            status_code=400, detail="GitHub token looks too short to be valid"
        )
    await set_setting(db, _GITHUB_TOKEN_KEY, token)
    return {"saved": True, "provider": "github"}


@router.delete("/github-token")
async def delete_github_token(
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Remove the DB-stored GitHub token (falls back to GITHUB_TOKEN env var)."""
    await set_setting(db, _GITHUB_TOKEN_KEY, "")
    return {"deleted": True, "provider": "github"}


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH14 §95 gap-closure (2026-08-12) — repo-scoped GitHub token.
# GitHub tokens are the one credential type genuinely likely to differ per
# repo (distinct write scopes/orgs/forks), unlike the installation-wide
# Anthropic/OpenAI keys above. Checked first by CredentialVault.load()
# (app/security/credential_vault.py) — app/api/agents.py's env-injection
# call sites already resolve the task's repo_id and pass it through; unset
# for a given repo, this falls back to the global token above unchanged.
# ---------------------------------------------------------------------------


@router.get("/repos/{repo_id}/github-token")
async def get_repo_github_token(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    from app.security.credential_vault import scoped_credential_key

    token = await get_setting(db, scoped_credential_key(_GITHUB_TOKEN_KEY, repo_id))
    return {
        "repoId": repo_id,
        "configured": bool(token),
        "masked": _mask(token) if token else None,
    }


@router.post("/repos/{repo_id}/github-token")
async def save_repo_github_token(
    repo_id: int,
    body: ApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Save/override this repo's own GitHub token."""
    from app.security.credential_vault import scoped_credential_key

    token = body.api_key.strip()
    if len(token) < 10:
        raise HTTPException(
            status_code=400, detail="GitHub token looks too short to be valid"
        )
    await set_setting(db, scoped_credential_key(_GITHUB_TOKEN_KEY, repo_id), token)
    return {"saved": True, "provider": "github", "repoId": repo_id}


@router.delete("/repos/{repo_id}/github-token")
async def delete_repo_github_token(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Remove this repo's override — reverts it to the global GitHub token."""
    from app.security.credential_vault import scoped_credential_key

    await delete_setting(db, scoped_credential_key(_GITHUB_TOKEN_KEY, repo_id))
    return {"deleted": True, "provider": "github", "repoId": repo_id}


# ---------------------------------------------------------------------------
# Custom secrets (Day 17 — Credential Vault). Arbitrary named secrets an
# agent's bash tool calls may need (e.g. a third-party API key a task's code
# integrates with) — never database/deploy credentials, see
# docs/DAY17_PLAN.md's plan/reality correction. Names must be valid env var
# identifiers since they're injected directly as env vars.
# ---------------------------------------------------------------------------

_SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Gap-closure (Audit 05 fix, SEC-05-011): credential_vault.py's own docstring
# states database_url is "deliberately NOT a vault-manageable credential" per
# CLAUDE.md's "no agent ever gets deploy credentials" rule — but that
# exclusion was only ever implemented as two hardcoded .pop() calls
# (GITHUB_TOKEN/ANTHROPIC_API_KEY) at the two agent-launch call sites, not as
# a restriction on what could be *stored* here in the first place. A custom
# secret literally named DATABASE_URL (a syntactically valid identifier) was
# previously accepted and would have been injected unexcluded into every
# coding agent's bash environment. Denylist matches case-insensitively since
# env var lookups on most shells are case-sensitive but a near-miss name is
# just as capable of causing confusion/collision.
_RESERVED_SECRET_NAMES = frozenset(
    {
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "JWT_SECRET_KEY",
        "CREDENTIAL_ENCRYPTION_KEY",
        "DEFAULT_ADMIN_PASSWORD",
        "VOYAGE_API_KEY",
        "GROQ_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
)


class CustomSecretRequest(BaseModel):
    name: str
    value: str


@router.get("/custom-secrets")
async def list_custom_secrets(
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Names only — never values."""
    keys = await list_setting_keys(db, _CUSTOM_SECRET_PREFIX)
    names = sorted(k[len(_CUSTOM_SECRET_PREFIX) :] for k in keys)
    return {"names": names}


@router.post("/custom-secrets")
async def save_custom_secret(
    body: CustomSecretRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    name = body.name.strip()
    if not _SECRET_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Secret name must be a valid env var identifier "
            "(letters, digits, underscore; cannot start with a digit).",
        )
    if name.upper() in _RESERVED_SECRET_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"{name!r} is a reserved/platform credential name and "
            "cannot be stored as a custom secret.",
        )
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Secret value cannot be empty.")
    await set_setting(db, _CUSTOM_SECRET_PREFIX + name, value)
    return {"saved": True, "name": name}


@router.delete("/custom-secrets/{name}")
async def delete_custom_secret(
    name: str,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    deleted = await delete_setting(db, _CUSTOM_SECRET_PREFIX + name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No custom secret named {name!r}")
    return {"deleted": True, "name": name}


# ---------------------------------------------------------------------------
# Verify endpoint — tests a key against the real API without saving it
# ---------------------------------------------------------------------------


@router.post("/verify-key")
async def verify_api_key(
    body: VerifyKeyRequest, _actor: str = Depends(require_authenticated)
) -> dict[str, Any]:
    """Test an API key against the provider's API and return ok/error."""
    provider = body.provider.lower().strip()
    key = body.api_key.strip()

    if provider == "anthropic":
        return await _verify_anthropic(key)
    elif provider == "openai":
        return await _verify_openai(key)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Use 'anthropic' or 'openai'.",
        )


async def _verify_anthropic(key: str) -> dict[str, Any]:
    if not key.startswith("sk-"):
        return {"ok": False, "error": "Key must start with 'sk-'"}
    try:
        import anthropic as _anthropic

        client = _anthropic.Anthropic(api_key=key)
        client.messages.create(
            model=get_settings().model_router,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {"ok": True, "provider": "anthropic"}
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "authentication" in msg.lower() or "invalid" in msg.lower():
            return {"ok": False, "error": "Invalid API key — authentication failed"}
        if "403" in msg:
            return {"ok": False, "error": "API key valid but lacks permissions"}
        return {"ok": False, "error": f"API error: {msg[:200]}"}


async def _verify_openai(key: str) -> dict[str, Any]:
    if not key.startswith("sk-"):
        return {"ok": False, "error": "Key must start with 'sk-'"}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key)
        client.models.list()
        return {"ok": True, "provider": "openai"}
    except Exception as exc:
        msg = str(exc)
        if (
            "401" in msg
            or "authentication" in msg.lower()
            or "incorrect" in msg.lower()
        ):
            return {"ok": False, "error": "Invalid API key — authentication failed"}
        if "403" in msg:
            return {"ok": False, "error": "API key valid but lacks permissions"}
        return {"ok": False, "error": f"API error: {msg[:200]}"}
