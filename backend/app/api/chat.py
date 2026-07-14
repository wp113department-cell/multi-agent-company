"""Chat API — SSE streaming endpoints for the interactive chat interface."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.chat import ChatSession, create_session, get_session, delete_session

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
async def create_chat_session(body: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new chat session for a repository."""
    session = create_session(repo_path=body.repo_path)
    return CreateSessionResponse(session_id=session.session_id)


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: SendMessageRequest) -> StreamingResponse:
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
    from app.agents.chat_agent import ChatAgent  # local import to avoid circular

    session = _require_session(session_id)
    if session.active:
        raise HTTPException(status_code=409, detail="Session already has an active message being processed")

    session.active = True

    # Launch agent in background — it pushes events to the queue
    agent = ChatAgent(session=session)
    asyncio.create_task(_run_agent(agent, body.message, session))

    return StreamingResponse(
        _event_stream(session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _run_agent(agent: Any, message: str, session: ChatSession) -> None:
    """Background task: run the agent and catch any unhandled exceptions."""
    try:
        await agent.run(message)
    except Exception as e:
        logger.exception("Unhandled error in chat agent")
        await session.push({"type": "error", "message": f"Internal error: {e}"})
        session.active = False


@router.post("/sessions/{session_id}/confirm")
async def confirm_action(session_id: str, body: ConfirmActionRequest) -> dict[str, str]:
    """
    Resolve a pending confirmation request (approve or deny a dangerous action).
    Called when the user clicks Approve/Deny in the UI.
    """
    session = _require_session(session_id)
    session.resolve_confirmation(body.action_id, body.approved)
    return {"status": "ok"}


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str) -> dict[str, object]:
    """Return the conversation history for a session."""
    session = _require_session(session_id)
    # Filter to only text content for the UI
    ui_history: list[dict[str, object]] = []
    for msg in session.history:
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
    return {"history": ui_history}


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str) -> dict[str, str]:
    """Close and clean up a chat session."""
    _require_session(session_id)
    delete_session(session_id)
    return {"status": "deleted"}
