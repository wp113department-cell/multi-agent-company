"""Chat session model — in-memory state + optional DB persistence.

Sessions are always held in-memory (for low-latency SSE streaming).
When a DB session factory is available, messages are also written to the
`chat_messages` table so history survives server restarts.

DB persistence is opt-in per-call: pass `db_factory` to `create_session()`
or call `load_history_from_db()` / `save_message_to_db()` explicitly.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChatSession:
    """Note (MASTER_AGENT_v2.md Phase 5.2): confirmation pause/resume used
    to live on this class via a bespoke asyncio.Event mechanism
    (request_confirmation()/resolve_confirmation()). That's been replaced
    by a real LangGraph interrupt()-based pause in
    app/agents/chat_agent.py::ChatAgent (._confirm()/.resume()) — see that
    module's docstring for the full design. This class now only owns what
    every session genuinely needs regardless of pause mechanism: history,
    the SSE event queue, and the "already processing a message" flag."""

    session_id: str
    repo_path: str
    # Stage 4 Cluster O Phase 1b (2026-08-05) — resolved once at session
    # creation (app/api/chat.py::create_chat_session) via
    # app.db.repository.resolve_repo_id_from_path, the one documented
    # exception to "never reverse-resolve from a path" (see that function's
    # own docstring). None means unscoped/global (INV-8) — correct when no
    # matching ready Repo row exists.
    repo_id: int | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    _queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    active: bool = False

    async def push(self, event: dict[str, Any]) -> None:
        await self._queue.put(event)


_sessions: dict[str, ChatSession] = {}


def create_session(repo_path: str, repo_id: int | None = None) -> ChatSession:
    sid = str(uuid.uuid4())
    session = ChatSession(session_id=sid, repo_path=repo_path, repo_id=repo_id)
    _sessions[sid] = session
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)


def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# DB persistence helpers
# ---------------------------------------------------------------------------


async def save_message_to_db(
    session_id: str,
    repo_path: str,
    role: str,
    content: str,
    db: Any,
) -> None:
    """Append one message to the chat_messages table. Never raises."""
    try:
        from sqlalchemy import text

        await db.execute(
            text(
                "INSERT INTO chat_messages (session_id, repo_path, role, content) "
                "VALUES (:sid, :repo, :role, :content)"
            ),
            {"sid": session_id, "repo": repo_path, "role": role, "content": content},
        )
        await db.commit()
    except Exception as exc:
        logger.warning(
            "Failed to persist chat message for session %s: %s", session_id, exc
        )


async def load_history_from_db(session_id: str, db: Any) -> list[dict[str, Any]]:
    """Load message history for a session from the DB. Returns [] on error.

    Blocker (audit_v1.md 4.4 #3): previously had no LIMIT at all — every
    message row for the session's entire lifetime, unbounded. Bounded here
    to the most recent chat_history_restore_limit messages (fetch newest-
    first with a LIMIT, so the query itself stays cheap regardless of how
    long-lived the session is, then reverse back to chronological order for
    the caller). ChatAgent's own condense step (see
    app.agents.chat_agent._call_llm_node) still runs on top of this bounded
    set for anything still over the token budget — this bound and that
    condense step are complementary, not alternatives.
    """
    try:
        from sqlalchemy import text

        from app.config import get_settings

        limit = get_settings().chat_history_restore_limit
        rows = await db.execute(
            text(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id = :sid ORDER BY created_at DESC LIMIT :limit"
            ),
            {"sid": session_id, "limit": limit},
        )
        newest_first = [
            {"role": str(r["role"]), "content": str(r["content"])}
            for r in rows.mappings().all()
        ]
        return list(reversed(newest_first))
    except Exception as exc:
        logger.warning(
            "Failed to load chat history for session %s: %s", session_id, exc
        )
        return []


async def get_or_restore_session(
    session_id: str, repo_path: str, db: Any
) -> ChatSession:
    """Return an in-memory session, restoring history from DB if the session was lost."""
    session = get_session(session_id)
    if session is None:
        # Stage 4 Cluster O Phase 1b (2026-08-05) — same resolution as
        # create_session's own real call site (app/api/chat.py), kept
        # consistent here so a second ChatSession-construction path
        # doesn't silently diverge and end up unscoped by omission.
        repo_id: int | None = None
        if db is not None:
            try:
                from app.db.repository import resolve_repo_id_from_path

                repo_id = await resolve_repo_id_from_path(db, repo_path)
            except Exception:
                repo_id = None
        session = ChatSession(
            session_id=session_id, repo_path=repo_path, repo_id=repo_id
        )
        _sessions[session_id] = session

    if not session.history and db is not None:
        session.history = await load_history_from_db(session_id, db)

    return session
