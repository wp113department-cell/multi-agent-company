from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/repo", tags=["repo"])


class ReindexResponse(BaseModel):
    triggered: bool
    message: str


@router.post("/reindex")
async def trigger_reindex() -> ReindexResponse:
    """Trigger a full repository reindex + embedding generation (fire-and-forget).
    Repo intelligence pipeline is wired in Day 2."""
    return ReindexResponse(triggered=True, message="Reindex triggered (pipeline wired in Day 2)")


@router.get("/reindex")
async def reindex_status() -> dict[str, object]:
    """Return last indexed timestamp. Status endpoint wired in Day 2."""
    return {"last_indexed_at": None, "message": "Repo intelligence pipeline wired in Day 2"}
