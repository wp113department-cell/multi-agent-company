"""Pre-dispatch refusal once the fleet-wide daily LLM budget is spent.

Production audit 09: without this, a run/approve/chat request was accepted,
queued a background run, and only then got blocked on its first LLM call —
the user saw a task go "blocked" with no clear reason. Endpoints that start
LLM work declare ``dependencies=[Depends(require_daily_budget)]`` and answer
429 with an explicit message instead.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.fleet import spend_guard


async def require_daily_budget() -> None:
    try:
        await spend_guard.check_before_dispatch()
    except spend_guard.DailyBudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
