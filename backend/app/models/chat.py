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
    session_id: str
    repo_path: str
    history: list[dict[str, Any]] = field(default_factory=list)
    _queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    _pending: dict[str, asyncio.Event] = field(default_factory=dict)
    _results: dict[str, bool] = field(default_factory=dict)
    active: bool = False

    async def push(self, event: dict[str, Any]) -> None:
        await self._queue.put(event)

    async def request_confirmation(
        self, action_id: str, description: str, details: str
    ) -> bool:
        """Pause the agent and ask the user to approve/deny an action."""
        ev = asyncio.Event()
        self._pending[action_id] = ev
        await self.push(
            {
                "type": "confirmation_required",
                "actionId": action_id,
                "description": description,
                "details": details,
            }
        )
        await ev.wait()
        return self._results.get(action_id, False)

    def resolve_confirmation(self, action_id: str, approved: bool) -> None:
        """Called by the confirm endpoint to resume the agent."""
        self._results[action_id] = approved
        ev = self._pending.pop(action_id, None)
        if ev:
            ev.set()


_sessions: dict[str, ChatSession] = {}


def create_session(repo_path: str) -> ChatSession:
    sid = str(uuid.uuid4())
    session = ChatSession(session_id=sid, repo_path=repo_path)
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
    """Load message history for a session from the DB. Returns [] on error."""
    try:
        from sqlalchemy import text

        rows = await db.execute(
            text(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id = :sid ORDER BY created_at ASC"
            ),
            {"sid": session_id},
        )
        return [
            {"role": str(r["role"]), "content": str(r["content"])}
            for r in rows.mappings().all()
        ]
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
        session = ChatSession(session_id=session_id, repo_path=repo_path)
        _sessions[session_id] = session

    if not session.history and db is not None:
        session.history = await load_history_from_db(session_id, db)

    return session
