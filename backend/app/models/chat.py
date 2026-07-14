"""In-memory chat session store — one session per browser tab."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any


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

    async def request_confirmation(self, action_id: str, description: str, details: str) -> bool:
        """Pause the agent and ask the user to approve/deny an action."""
        ev = asyncio.Event()
        self._pending[action_id] = ev
        await self.push({
            "type": "confirmation_required",
            "actionId": action_id,
            "description": description,
            "details": details,
        })
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
