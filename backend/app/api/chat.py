"""Chat API — SSE streaming endpoints for the interactive chat interface."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.budget_gate import require_daily_budget
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.middleware.rbac import require_approver, require_authenticated
from app.models.chat import (
    ChatSession,
    create_session,
    get_session,
    delete_session,
    get_or_restore_session,
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
    # Sol A03: a project (preferred — the server resolves its folder) or the
    # path of a registered project/repository folder; nothing else.
    repo_path: str | None = None
    # C2: the project the chat belongs to (shown in the list of past chats)
    project_id: int | None = None


class CreateSessionResponse(BaseModel):
    session_id: str


class ChatAttachment(BaseModel):
    """C1: a file the user attached to a chat message (base64 content)."""

    name: str = Field(..., min_length=1, max_length=200)
    media_type: str = Field(..., max_length=100)
    data: str


class SendMessageRequest(BaseModel):
    message: str
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=5)


class ConfirmActionRequest(BaseModel):
    action_id: str
    approved: bool
    # AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) — carries the chosen
    # option's id back for a paused ask_human_to_choose call; None (the
    # default) for every plain approve/deny confirmation, unchanged.
    selected: str | None = None
    # AUDIT_Q_BATCH07 §39 gap-closure (2026-08-11) — "'Don't ask again this
    # session': NO — not found." Explicit opt-in per confirmation; defaults
    # to False so every existing client that doesn't send this field keeps
    # behaving exactly as before.
    remember: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_session(session_id: str) -> ChatSession:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return session


async def _require_session_restoring(session_id: str) -> ChatSession:
    """_require_session, but a session lost to a restart is rebuilt from the chat_messages
    table (get_or_restore_session existed — and was imported here with `noqa: F401` — but was
    never called, so every conversation 404'd after a restart and its stored history was
    unreachable for continuing)."""
    session = get_session(session_id)
    if session is not None:
        return session
    from sqlalchemy import text

    from app.db.session import get_session_factory

    try:
        async with get_session_factory()() as db:
            # C2: a listed chat knows its folder even before its first message
            row = (
                await db.execute(
                    text(
                        "SELECT repo_path FROM chat_sessions WHERE id = :sid "
                        "UNION ALL (SELECT repo_path FROM chat_messages "
                        "WHERE session_id = :sid ORDER BY created_at DESC LIMIT 1) "
                        "LIMIT 1"
                    ),
                    {"sid": session_id},
                )
            ).first()
            if row is not None:
                return await get_or_restore_session(session_id, str(row[0]), db)
    except Exception:
        logger.warning("could not restore chat session %s", session_id, exc_info=True)
    raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")


# ---------------------------------------------------------------------------
# C1 (2026-10-09): attachments — images go to the model as pictures; PDFs and
# text/code files become text in the message. Limits keep cost and memory sane.
# ---------------------------------------------------------------------------

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_PDF_BYTES = 20 * 1024 * 1024
_MAX_TEXT_BYTES = 300 * 1024
_MAX_TEXT_CHARS = 60_000


def _prepare_attachments(
    attachments: list[ChatAttachment],
) -> tuple[str, list[dict[str, Any]]]:
    import base64
    import binascii

    extra: list[str] = []
    images: list[dict[str, Any]] = []
    for att in attachments:
        try:
            raw = base64.b64decode(att.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(
                status_code=400, detail=f"{att.name!r} could not be read."
            ) from None
        media = att.media_type.lower()
        if media in _IMAGE_TYPES:
            if len(raw) > _MAX_IMAGE_BYTES:
                raise HTTPException(
                    status_code=400, detail=f"Image {att.name!r} is larger than 5 MB."
                )
            images.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media, "data": att.data},
                    # stripped before the block reaches the model or the DB
                    "_name": att.name,
                }
            )
        elif media == "application/pdf" or att.name.lower().endswith(".pdf"):
            if len(raw) > _MAX_PDF_BYTES:
                raise HTTPException(
                    status_code=400, detail=f"PDF {att.name!r} is larger than 20 MB."
                )
            from app.api.tasks import _extract_pdf_text

            text = _extract_pdf_text(raw, att.name)[:_MAX_TEXT_CHARS]
            extra.append(f"\n\n--- Attached PDF: {att.name} ---\n{text}")
        else:
            if len(raw) > _MAX_TEXT_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{att.name!r} is larger than 300 KB; attach a smaller part.",
                )
            if b"\x00" in raw:
                raise HTTPException(
                    status_code=400,
                    detail=f"{att.name!r} is not a text file (images, PDFs and "
                    "text/code files can be attached).",
                )
            text = raw.decode("utf-8", errors="replace")[:_MAX_TEXT_CHARS]
            extra.append(f"\n\n--- Attached file: {att.name} ---\n{text}")
    for img in images:
        img.pop("_name", None)
    return "".join(extra), images


def _without_image_data(content: Any) -> Any:
    """Stored history keeps a note instead of the picture itself."""
    if not isinstance(content, list):
        return content
    return [
        (
            {"type": "text", "text": "[an image was attached]"}
            if isinstance(block, dict) and block.get("type") == "image"
            else block
        )
        for block in content
    ]


async def _authorized_chat_folder(db: AsyncSession, body: CreateSessionRequest) -> str:
    """Sol A03 (2026-10-09): the folder a chat (and its terminal, which
    mounts it into the sandbox) works in is resolved on the server: from
    the chosen project, or — for a path — only when it is a registered
    project/repository folder (or inside one). Nonexistent folders and
    folders reached through a symlink are refused. It used to be any path
    the caller sent."""
    import os

    from sqlalchemy import select

    from app.db.models import Project, Repo
    from app.services.workspace_service import is_within

    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        repo = await db.get(Repo, project.repo_id) if project.repo_id else None
        folder = (repo.local_path if repo and repo.status == "ready" else None) or (
            project.local_path if repo is None else None
        )
        if not folder:
            raise HTTPException(
                status_code=400,
                detail="This project's files are not ready yet (still downloading?).",
            )
    elif body.repo_path:
        folder = body.repo_path
        roots = [
            str(r) for r in (await db.execute(select(Repo.local_path))).scalars() if r
        ] + [
            str(p)
            for p in (await db.execute(select(Project.local_path))).scalars()
            if p
        ]
        if not any(is_within(folder, root) for root in roots):
            raise HTTPException(
                status_code=403,
                detail="Choose one of your projects: chats can only work in a "
                "registered project folder.",
            )
    else:
        raise HTTPException(status_code=400, detail="Choose a project for the chat.")
    absolute = os.path.abspath(folder)
    if os.path.realpath(absolute) != absolute:
        raise HTTPException(
            status_code=403, detail="The project folder may not be a symbolic link."
        )
    if not os.path.isdir(absolute):
        raise HTTPException(
            status_code=400, detail="The project folder does not exist."
        )
    return absolute


async def _touch_chat_record(db: AsyncSession, session_id: str, message: str) -> None:
    """C2: a new message moves the chat to the top of the list; the first
    one names it. Non-fatal: the list must never block a chat turn."""
    from datetime import datetime, timezone

    from app.db.models import ChatSessionRecord

    try:
        rec = await db.get(ChatSessionRecord, session_id)
        if rec is None:
            return
        rec.last_message_at = datetime.now(timezone.utc)
        if rec.title == "New chat" and message.strip():
            first_line = message.strip().splitlines()[0]
            rec.title = first_line[:80] + ("…" if len(first_line) > 80 else "")
        await db.commit()
    except Exception:
        logger.debug("chat list update skipped", exc_info=True)
        await db.rollback()


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
    _actor: str = Depends(require_approver),
) -> CreateSessionResponse:
    """Create a new chat session for a repository."""
    folder = await _authorized_chat_folder(db, body)
    # Stage 4 Cluster O Phase 1b (2026-08-05) — resolved once here, at
    # session creation, per CLUSTER_O_DESIGN.md §2 Q2 ("resolved once at
    # the boundary, carried for the unit of work's lifetime"). Non-fatal:
    # a resolution failure must never block chat session creation.
    from app.db.repository import resolve_repo_id_from_path

    try:
        repo_id = await resolve_repo_id_from_path(db, folder)
    except Exception:
        logger.debug("chat session repo_id resolution skipped", exc_info=True)
        repo_id = None

    session = create_session(repo_path=folder, repo_id=repo_id)
    # C2: the chat appears in the list of past chats
    from app.db.models import ChatSessionRecord

    db.add(
        ChatSessionRecord(
            id=session.session_id,
            project_id=body.project_id,
            repo_path=folder,
            title="New chat",
            created_by=_actor,
        )
    )
    await db.commit()
    return CreateSessionResponse(session_id=session.session_id)


@router.post(
    "/sessions/{session_id}/messages", dependencies=[Depends(require_daily_budget)]
)
@limiter.limit(get_settings().rate_limit_agents)
async def send_message(
    request: Request,
    session_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
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

    session = await _require_session_restoring(session_id)
    if session.active:
        raise HTTPException(
            status_code=409,
            detail="Session already has an active message being processed",
        )

    extra_text, images = _prepare_attachments(body.attachments)
    if not body.message.strip() and not body.attachments:
        raise HTTPException(status_code=400, detail="Type a message or attach a file.")
    message = body.message + extra_text
    session.active = True
    await _touch_chat_record(
        db, session_id, body.message or ", ".join(a.name for a in body.attachments)
    )

    # Launch agent in background — it pushes events to the queue. Reused
    # (not freshly constructed) so the same ChatAgent instance — and thus
    # the same in-process LangGraph checkpointer/thread_id — is available
    # if this turn pauses at a confirmation and confirm_action() needs to
    # resume() it later (MASTER_AGENT_v2.md Phase 5.2).
    agent = get_or_create_chat_agent(session)
    factory = get_session_factory()
    asyncio.create_task(_run_agent(agent, message, session, factory, images))

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
                    content = _without_image_data(msg.get("content", ""))
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
    agent: Any,
    message: str,
    session: ChatSession,
    db_factory: Any,
    images: list[dict[str, Any]] | None = None,
) -> None:
    """Background task: run the agent, then persist user message + assistant reply to DB."""
    history_len_before = len(session.history)
    try:
        if images:
            await agent.run(message, images=images)
        else:
            await agent.run(message)
    except Exception as e:
        logger.exception("Unhandled error in chat agent")
        await session.push({"type": "error", "message": f"Internal error: {e}"})
        session.active = False
        return

    await _persist_new_messages(session, history_len_before, db_factory)


async def _resume_agent(
    agent: Any,
    action_id: str,
    approved: bool,
    session: ChatSession,
    db_factory: Any,
    selected: str | None = None,
    remember: bool = False,
) -> None:
    """Background task: resume a paused turn after a confirmation decision,
    then persist any messages the continuation produced. Mirrors
    _run_agent()'s error handling exactly (MASTER_AGENT_v2.md Phase 5.2)."""
    history_len_before = len(session.history)
    try:
        resumed = await agent.resume(
            action_id, approved, selected=selected, remember=remember
        )
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
    _actor: str = Depends(require_approver),
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

    session = await _require_session_restoring(session_id)
    agent = get_or_create_chat_agent(session)
    factory = get_session_factory()
    asyncio.create_task(
        _resume_agent(
            agent,
            body.action_id,
            body.approved,
            session,
            factory,
            body.selected,
            body.remember,
        )
    )
    return {"status": "ok"}


@router.post("/sessions/{session_id}/stop")
async def stop_chat_turn(
    session_id: str,
    _actor: str = Depends(require_approver),
) -> dict[str, str]:
    """UI gap-closure (2026-09-25) — a real Stop control for an
    in-progress chat turn. Before this, the frontend's own
    AbortController only ever cancelled the CLIENT's fetch connection
    (see _event_stream's own comment on send_message) — it never reached
    this server-side background task at all, so typing/clicking "stop"
    had no effect on the agent. This sets a flag ChatAgent checks between
    graph nodes (not mid-tool-call — a bash command already dispatched
    still runs to completion; only the NEXT LLM call or queued tool call
    is skipped) and pushes a real, distinguishable 'done' event
    ({"stopped": true}) once the graph actually reaches finalize.

    A no-op (not an error) if there's no turn in progress — matches
    confirm_action's own tolerance for a stale/no-op call."""
    from app.agents.chat_agent import get_or_create_chat_agent

    session = await _require_session_restoring(session_id)
    agent = get_or_create_chat_agent(session)
    agent.request_stop()
    return {"status": "stop_requested"}


@router.get("/sessions/{session_id}/history")
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
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
    session_id: str, _actor: str = Depends(require_approver)
) -> dict[str, str]:
    """Close and clean up a chat session."""
    from app.agents.chat_agent import delete_chat_agent

    _require_session(session_id)
    delete_session(session_id)
    delete_chat_agent(session_id)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# C2 (2026-10-09): the list of past chats — reopen, rename, delete
# ---------------------------------------------------------------------------


class RenameChatRequest(BaseModel):
    title: str


async def _owned_chat(db: AsyncSession, session_id: str, actor: str) -> Any:
    """The chat's list record, if this user may manage it (its creator; chats
    from before C2 have no recorded owner and are shared)."""
    from app.db.models import ChatSessionRecord

    rec = await db.get(ChatSessionRecord, session_id)
    if rec is None or (rec.created_by not in (None, actor)):
        raise HTTPException(status_code=404, detail="Chat not found")
    return rec


def _chat_dict(rec: Any) -> dict[str, object]:
    return {
        "id": rec.id,
        "title": rec.title,
        "projectId": rec.project_id,
        "repoPath": rec.repo_path,
        "createdAt": rec.created_at.isoformat() if rec.created_at else None,
        "lastMessageAt": (
            rec.last_message_at.isoformat() if rec.last_message_at else None
        ),
    }


@router.get("/sessions")
async def list_chats(
    project_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_authenticated),
) -> dict[str, object]:
    """This user's past chats, newest first (optionally for one project)."""
    from sqlalchemy import or_, select

    from app.db.models import ChatSessionRecord

    q = (
        select(ChatSessionRecord)
        .where(
            or_(
                ChatSessionRecord.created_by == actor,
                ChatSessionRecord.created_by.is_(None),
            )
        )
        .order_by(ChatSessionRecord.last_message_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if project_id is not None:
        q = q.where(ChatSessionRecord.project_id == project_id)
    rows = (await db.execute(q)).scalars().all()
    return {"chats": [_chat_dict(r) for r in rows]}


@router.patch("/sessions/{session_id}")
async def rename_chat(
    session_id: str,
    body: RenameChatRequest,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_approver),
) -> dict[str, object]:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Give the chat a name.")
    rec = await _owned_chat(db, session_id, actor)
    rec.title = title[:200]
    await db.commit()
    return _chat_dict(rec)


@router.delete("/history/{session_id}")
async def delete_chat_forever(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_approver),
) -> dict[str, str]:
    """Remove a chat and its messages permanently (DELETE /sessions/{id}
    only closes the live conversation and keeps the history)."""
    from sqlalchemy import text

    from app.agents.chat_agent import delete_chat_agent

    rec = await _owned_chat(db, session_id, actor)
    if rec is not None:
        await db.delete(rec)
    await db.execute(
        text("DELETE FROM chat_messages WHERE session_id = :sid"), {"sid": session_id}
    )
    await db.commit()
    delete_session(session_id)
    delete_chat_agent(session_id)
    return {"status": "deleted"}
