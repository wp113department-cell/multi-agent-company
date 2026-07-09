"""Executive Agent — plain-language goal → epics + business summary."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.config import get_settings
from app.db.models import Epic, Goal

logger = logging.getLogger(__name__)


async def run_executive(
    goal_text: str,
    db: AsyncSession,
) -> tuple[str, list[str], str | None]:
    """
    Convert a plain-language goal into epics and a business-language summary.

    Returns (goal_id, epic_ids, error).  On success error is None.
    The Goal and Epic ORM rows are written to `db` and flushed (not committed —
    caller owns the transaction).
    """
    settings = get_settings()
    max_epics = settings.executive_max_epics_per_goal

    role_content = _load_role_with_max(max_epics)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Goal: {goal_text}"},
    ]

    try:
        final_text, tokens_in, tokens_out, *_ = run_agent(
            role_name="executive",
            model=settings.model_router,
            messages=messages,
            tools=[],
            tool_handlers={},
            max_turns=3,
        )
    except Exception as exc:
        logger.exception("Executive agent call failed")
        return "", [], str(exc)

    # Parse JSON response
    try:
        data = _parse_json(final_text)
    except ValueError as exc:
        return "", [], f"JSON parse error: {exc} — raw: {final_text[:300]}"

    raw_epics: list[dict[str, str]] = data.get("epics", [])
    summary: str = data.get("summary", "")

    if not raw_epics:
        return "", [], "Executive agent returned no epics"

    # Cap to configured max
    raw_epics = raw_epics[:max_epics]

    # Create Goal row
    goal_id = str(uuid.uuid4())
    epic_ids: list[str] = []

    for ep in raw_epics:
        epic_id = str(uuid.uuid4())
        epic = Epic(
            epic_id=epic_id,
            title=ep.get("title", "Untitled epic")[:500],
            description=ep.get("description", ""),
            status="pending",
        )
        db.add(epic)
        epic_ids.append(epic_id)

    goal = Goal(
        goal_id=goal_id,
        text=goal_text,
        status="processing",
        epic_ids=epic_ids,
        summary=summary,
    )
    db.add(goal)
    await db.flush()

    logger.info(
        "Executive created goal %s with %d epics (%d tokens in, %d out)",
        goal_id,
        len(epic_ids),
        tokens_in,
        tokens_out,
    )
    return goal_id, epic_ids, None


def _load_role_with_max(max_epics: int) -> str:
    """Load executive role markdown with max_epics substituted."""
    from app.agents.base import load_role
    text = load_role("executive")
    return text.replace("{max_epics}", str(max_epics))


def _parse_json(text: str) -> dict[str, Any]:
    """Extract first JSON object from text (tolerates surrounding prose)."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    return json.loads(text[start:end])  # type: ignore[no-any-return]
