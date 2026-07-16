"""Executive Agent — plain-language goal → epics + business summary.

Session 4 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: medium — writes Goal + Epic rows to DB).
- Added _register() at module level.
- No tools: run_agent_graph with tools=[] does a single LLM call, returns text in messages.
- final_text extracted via _last_assistant_text(final_state["messages"]) for JSON parsing.
- {max_epics} role-placeholder: include constraint in initial_message since run_agent_graph
  loads the role file directly without string substitution.
- _load_role_with_max kept for backward compat but no longer called in the hot path.
- External interface (async run_executive signature + return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.config import get_settings
from app.db.models import Epic, Goal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "executive",
    "description": "Converts a plain-language goal into structured epics and a business summary.",
    "allowed_tools": [],  # pure text generation — no tool calls
    "input_types": ["goal_text"],
    "output_types": ["goal_id", "epic_ids"],
    "side_effects": ["write_db"],
    "permissions": ["write_db"],
    "risk_level": "medium",
    "expected_verification": {},
    "dependencies": [],
}

# ---------------------------------------------------------------------------
# Verification contract — no tools, no mutation tracking needed
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={},
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Extract the last text response from the assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
    return ""


def _load_role_with_max(max_epics: int) -> str:
    """Load executive role markdown with max_epics substituted (kept for compat)."""
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


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged (async)
# ---------------------------------------------------------------------------

async def run_executive(
    goal_text: str,
    db: AsyncSession,
) -> tuple[str, list[str], str | None]:
    """Convert a plain-language goal into epics and a business-language summary.

    Returns (goal_id, epic_ids, error). On success error is None.
    Goal and Epic ORM rows are written to db and flushed (caller owns the transaction).
    """
    settings = get_settings()
    max_epics = settings.executive_max_epics_per_goal

    # {max_epics} in the role file is unsubstituted by run_agent_graph; include
    # the constraint explicitly in the user message so the LLM honours it.
    initial_message = (
        f"Goal: {goal_text}\n\n"
        f"Generate at most {max_epics} epics."
    )

    try:
        final_state = run_agent_graph(
            role_name="executive",
            model=settings.model_router,
            tools=[],
            tool_handlers={},
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            max_turns=3,
        )
    except Exception as exc:
        logger.exception("Executive agent call failed")
        return "", [], str(exc)

    final_text = _last_assistant_text(final_state.get("messages", []))
    tokens_in = final_state.get("tokens_in", 0)
    tokens_out = final_state.get("tokens_out", 0)

    try:
        data = _parse_json(final_text)
    except ValueError as exc:
        return "", [], f"JSON parse error: {exc} — raw: {final_text[:300]}"

    raw_epics: list[dict[str, str]] = data.get("epics", [])
    summary: str = data.get("summary", "")

    if not raw_epics:
        return "", [], "Executive agent returned no epics"

    raw_epics = raw_epics[:max_epics]

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
        goal_id, len(epic_ids), tokens_in, tokens_out,
    )
    return goal_id, epic_ids, None


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------

def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["goal_decomposition", "epic_generation", "executive_planning"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("executive")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
