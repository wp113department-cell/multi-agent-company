"""Chat API — SSE streaming endpoints for the interactive chat interface."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.middleware.rbac import require_authenticated
from app.models.chat import (
    ChatSession,
    create_session,
    get_session,
    delete_session,
    get_or_restore_session,  # noqa: F401
    load_history_from_db,
    save_message_to_db,
)
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    repo_path: str


class CreateSessionResponse(BaseModel):
    session_id: str


class SendMessageRequest(BaseModel):
    message: str


class ConfirmActionRequest(BaseModel):
    action_id: str
    approved: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_session(session_id: str) -> ChatSession:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return session


async def _event_stream(session: ChatSession) -> AsyncGenerator[str, None]:
    """
    Drain the session queue and format events as SSE.
    Stops when a 'done' or 'error' event is received.
    """
    while True:
        try:
            event = await asyncio.wait_for(session._queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            # Keep-alive ping
            yield ": ping\n\n"
            continue

        data = json.dumps(event)
        yield f"data: {data}\n\n"

        event_type = event.get("type", "")
        if event_type in ("done", "error"):
            session.active = False
            break


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_chat_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> CreateSessionResponse:
    """Create a new chat session for a repository."""
    # Stage 4 Cluster O Phase 1b (2026-08-05) — resolved once here, at
    # session creation, per CLUSTER_O_DESIGN.md §2 Q2 ("resolved once at
    # the boundary, carried for the unit of work's lifetime"). Non-fatal:
    # a resolution failure must never block chat session creation.
    from app.db.repository import resolve_repo_id_from_path

    try:
        repo_id = await resolve_repo_id_from_path(db, body.repo_path)
    except Exception:
        logger.debug("chat session repo_id resolution skipped", exc_info=True)
        repo_id = None

    session = create_session(repo_path=body.repo_path, repo_id=repo_id)
    return CreateSessionResponse(session_id=session.session_id)


@router.post("/sessions/{session_id}/messages")
@limiter.limit(get_settings().rate_limit_agents)
async def send_message(
    request: Request,
    session_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> StreamingResponse:
    """
    Send a user message and stream the agent's response as SSE.

    Response format: text/event-stream
    Each event is a JSON object with a 'type' field:
      - text_delta               : {"type": "text_delta", "text": "..."}
      - thinking                 : {"type": "thinking", "iteration": N}
      - tool_call                : {"type": "tool_call", "tool_name": "...", "tool_input": {...}, "tool_use_id": "..."}
      - tool_result              : {"type": "tool_result", "tool_name": "...", "output": "...", "tool_use_id": "..."}
      - confirmation_required    : {"type": "confirmation_required", "actionId": "...", "description": "...", "details": "..."}
      - done                     : {"type": "done"}
      - error                    : {"type": "error", "message": "..."}
    """
    from app.agents.chat_agent import get_or_create_chat_agent  # avoid circular import
    from app.db.session import get_session_factory

    session = _require_session(session_id)
    if session.active:
        raise HTTPException(
            status_code=409,
            detail="Session already has an active message being processed",
        )

    session.active = True

    # Launch agent in background — it pushes events to the queue. Reused
    # (not freshly constructed) so the same ChatAgent instance — and thus
    # the same in-process LangGraph checkpointer/thread_id — is available
    # if this turn pauses at a confirmation and confirm_action() needs to
    # resume() it later (MASTER_AGENT_v2.md Phase 5.2).
    agent = get_or_create_chat_agent(session)
    factory = get_session_factory()
    asyncio.create_task(_run_agent(agent, body.message, session, factory))

    return StreamingResponse(
        _event_stream(session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions/{session_id}/stream")
async def stream_chat_session(
    session_id: str,
    _actor: str = Depends(require_authenticated),
) -> StreamingResponse:
    """Reattach to an in-progress turn's event stream after a dropped connection.

    The agent already runs as a background task decoupled from the
    originating HTTP connection (see send_message/_run_agent) — a client
    network drop does not stop it, it just stops delivery. This lets the
    frontend re-subscribe to the same session._queue via a plain GET (usable
    with EventSource, unlike the POST that starts a turn) and keep receiving
    events through to a real 'done'/'error' terminal event, mirroring
    GET /api/tasks/{id}/stream's reconnect model.
    """
    session = _require_session(session_id)
    if not session.active:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id!r} has no message currently streaming",
        )
    return StreamingResponse(
        _event_stream(session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _persist_new_messages(
    session: ChatSession, history_len_before: int, db_factory: Any
) -> None:
    """Persist whatever messages were appended to session.history since
    history_len_before. Shared by the initial dispatch and by a resumed-
    after-confirmation continuation (MASTER_AGENT_v2.md Phase 5.2) — a
    turn can now legitimately produce history in more than one dispatch
    if it paused at a confirmation in between."""
    new_messages = session.history[history_len_before:]
    if new_messages and db_factory is not None:
        try:
            async with db_factory() as db:
                for msg in new_messages:
                    role = str(msg.get("role", ""))
                    content = msg.get("content", "")
                    text = content if isinstance(content, str) else json.dumps(content)
                    await save_message_to_db(
                        session.session_id, session.repo_path, role, text, db
                    )
        except Exception as exc:
            logger.warning(
                "Chat history persistence failed for session %s: %s",
                session.session_id,
                exc,
            )


async def _run_agent(
    agent: Any, message: str, session: ChatSession, db_factory: Any
) -> None:
    """Background task: run the agent, then persist user message + assistant reply to DB."""
    history_len_before = len(session.history)
    try:
        await agent.run(message)
    except Exception as e:
        logger.exception("Unhandled error in chat agent")
        await session.push({"type": "error", "message": f"Internal error: {e}"})
        session.active = False
        return

    await _persist_new_messages(session, history_len_before, db_factory)


async def _resume_agent(
    agent: Any, action_id: str, approved: bool, session: ChatSession, db_factory: Any
) -> None:
    """Background task: resume a paused turn after a confirmation decision,
    then persist any messages the continuation produced. Mirrors
    _run_agent()'s error handling exactly (MASTER_AGENT_v2.md Phase 5.2)."""
    history_len_before = len(session.history)
    try:
        resumed = await agent.resume(action_id, approved)
        if not resumed:
            # Stale/mismatched confirm — nothing ran, nothing to persist,
            # and the turn is still genuinely paused: leave session.active
            # as-is rather than guessing at a terminal state.
            return
    except Exception as e:
        logger.exception("Unhandled error resuming chat agent")
        await session.push({"type": "error", "message": f"Internal error: {e}"})
        session.active = False
        return

    await _persist_new_messages(session, history_len_before, db_factory)


@router.post("/sessions/{session_id}/confirm")
async def confirm_action(
    session_id: str,
    body: ConfirmActionRequest,
    _actor: str = Depends(require_authenticated),
) -> dict[str, str]:
    """
    Resolve a pending confirmation request (approve or deny a dangerous action).
    Called when the user clicks Approve/Deny in the UI.

    MASTER_AGENT_v2.md Phase 5.2 — this now resumes a real LangGraph
    interrupt() (app/agents/chat_agent.py::ChatAgent.resume()) rather than
    setting an asyncio.Event. Fired as a background task, same as the
    initial send: the client's existing SSE stream (opened by
    POST /messages, still listening on session._queue) keeps receiving
    whatever further events the resumed turn produces, all the way to a
    real 'done'.
    """
    from app.agents.chat_agent import get_or_create_chat_agent
    from app.db.session import get_session_factory

    session = _require_session(session_id)
    agent = get_or_create_chat_agent(session)
    factory = get_session_factory()
    asyncio.create_task(
        _resume_agent(agent, body.action_id, body.approved, session, factory)
    )
    return {"status": "ok"}


@router.get("/sessions/{session_id}/history")
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return the conversation history for a session.

    Falls back to DB if the session was dropped from memory (e.g. server restart).
    """
    session = get_session(session_id)
    if session is not None:
        source_history = session.history
    else:
        # Session lost from memory — read from DB directly
        source_history = await load_history_from_db(session_id, db)

    # Filter to only text content for the UI
    ui_history: list[dict[str, object]] = []
    for msg in source_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            ui_history.append({"role": role, "content": content})
        elif isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            combined = "\n".join(text_parts)
            if combined.strip():
                ui_history.append({"role": role, "content": combined})
    return {"history": ui_history, "session_id": session_id}


@router.delete("/sessions/{session_id}")
async def close_session(
    session_id: str, _actor: str = Depends(require_authenticated)
) -> dict[str, str]:
    """Close and clean up a chat session."""
    from app.agents.chat_agent import delete_chat_agent

    _require_session(session_id)
    delete_session(session_id)
    delete_chat_agent(session_id)
    return {"status": "deleted"}
