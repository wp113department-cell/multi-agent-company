"""Settings API — runtime-configurable values (API keys, etc.)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.db.repository import get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

_ANTHROPIC_KEY = "anthropic_api_key"


class ApiKeyRequest(BaseModel):
    api_key: str


@router.get("")
async def get_settings_view(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return current settings. API key is masked — shows only first 8 chars."""
    settings = get_settings()
    db_key = await get_setting(db, _ANTHROPIC_KEY)
    effective_key = db_key or settings.anthropic_api_key
    masked = (effective_key[:8] + "..." + effective_key[-4:]) if len(effective_key) > 12 else ("set" if effective_key else "")
    return {
        "anthropicKeySet": bool(effective_key),
        "anthropicKeyMasked": masked,
        "anthropicKeySource": "database" if db_key else ("env" if settings.anthropic_api_key else "none"),
        "usingGroq": settings.use_groq,
        "modelPlanner": settings.model_planner,
        "modelCoder": settings.model_coder,
    }


@router.post("/api-key")
async def save_api_key(body: ApiKeyRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Save or update the Anthropic API key in the database."""
    key = body.api_key.strip()
    if not key.startswith("sk-"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid API key — must start with 'sk-'")

    await set_setting(db, _ANTHROPIC_KEY, key)

    # Apply immediately without restart
    from app.agents.base import set_api_key_override
    set_api_key_override(key)

    return {"saved": True, "source": "database"}


@router.delete("/api-key")
async def delete_api_key(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Remove the DB-stored API key (will fall back to env var)."""
    from app.agents.base import set_api_key_override
    await set_setting(db, _ANTHROPIC_KEY, "")
    set_api_key_override("")
    return {"deleted": True}
