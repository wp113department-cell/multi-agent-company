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


@router.get("")
async def get_settings_view(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
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
        "usingGroq": settings.use_groq,
        "modelPlanner": settings.model_planner,
        "modelCoder": settings.model_coder,
    }


# ---------------------------------------------------------------------------
# Anthropic key
# ---------------------------------------------------------------------------


@router.post("/api-key")
async def save_api_key(
    body: ApiKeyRequest, db: AsyncSession = Depends(get_db)
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
async def delete_api_key(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
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
    body: ApiKeyRequest, db: AsyncSession = Depends(get_db)
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
async def delete_openai_key(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
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
    body: ApiKeyRequest, db: AsyncSession = Depends(get_db)
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
async def delete_github_token(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Remove the DB-stored GitHub token (falls back to GITHUB_TOKEN env var)."""
    await set_setting(db, _GITHUB_TOKEN_KEY, "")
    return {"deleted": True, "provider": "github"}


# ---------------------------------------------------------------------------
# Custom secrets (Day 17 — Credential Vault). Arbitrary named secrets an
# agent's bash tool calls may need (e.g. a third-party API key a task's code
# integrates with) — never database/deploy credentials, see
# docs/DAY17_PLAN.md's plan/reality correction. Names must be valid env var
# identifiers since they're injected directly as env vars.
# ---------------------------------------------------------------------------

_SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CustomSecretRequest(BaseModel):
    name: str
    value: str


@router.get("/custom-secrets")
async def list_custom_secrets(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Names only — never values."""
    keys = await list_setting_keys(db, _CUSTOM_SECRET_PREFIX)
    names = sorted(k[len(_CUSTOM_SECRET_PREFIX) :] for k in keys)
    return {"names": names}


@router.post("/custom-secrets")
async def save_custom_secret(
    body: CustomSecretRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    name = body.name.strip()
    if not _SECRET_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Secret name must be a valid env var identifier "
            "(letters, digits, underscore; cannot start with a digit).",
        )
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Secret value cannot be empty.")
    await set_setting(db, _CUSTOM_SECRET_PREFIX + name, value)
    return {"saved": True, "name": name}


@router.delete("/custom-secrets/{name}")
async def delete_custom_secret(
    name: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    deleted = await delete_setting(db, _CUSTOM_SECRET_PREFIX + name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No custom secret named {name!r}")
    return {"deleted": True, "name": name}


# ---------------------------------------------------------------------------
# Verify endpoint — tests a key against the real API without saving it
# ---------------------------------------------------------------------------


@router.post("/verify-key")
async def verify_api_key(body: VerifyKeyRequest) -> dict[str, Any]:
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
            model="claude-haiku-4-5-20251001",
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
