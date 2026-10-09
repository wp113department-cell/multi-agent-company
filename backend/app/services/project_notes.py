"""Project notes: memory the user can see and edit (C3, 2026-10-09).

The chat already learns from every turn (app.memory.store, repo-scoped),
but that memory is found by similarity and was invisible. Project notes are
the explicit part: short facts and decisions the user writes down ("we use
pnpm", "never touch the payments module"); every chat in the project gets
all of them with every message. Stored per project; removed with it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

MAX_NOTES = 30
MAX_NOTE_CHARS = 500


def notes_key(project_id: int) -> str:
    return f"project-notes:{project_id}"


async def get_notes(db: AsyncSession, project_id: int) -> list[dict[str, Any]]:
    from app.db.repository import get_setting

    raw = await get_setting(db, notes_key(project_id))
    try:
        notes = json.loads(raw) if raw else []
    except ValueError:
        notes = []
    return [n for n in notes if isinstance(n, dict) and n.get("text")]


async def _save(db: AsyncSession, project_id: int, notes: list[dict[str, Any]]) -> None:
    from app.db.repository import set_setting

    await set_setting(db, notes_key(project_id), json.dumps(notes))


async def add_note(
    db: AsyncSession, project_id: int, text: str, actor: str | None
) -> list[dict[str, Any]]:
    text = " ".join(text.split())[:MAX_NOTE_CHARS]
    if not text:
        raise ValueError("Write something to remember.")
    notes = await get_notes(db, project_id)
    if len(notes) >= MAX_NOTES:
        raise ValueError(
            f"A project can keep up to {MAX_NOTES} notes; delete one first."
        )
    notes.append(
        {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "createdBy": actor,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    await _save(db, project_id, notes)
    return notes


async def delete_note(
    db: AsyncSession, project_id: int, note_id: str
) -> list[dict[str, Any]]:
    notes = [n for n in await get_notes(db, project_id) if n.get("id") != note_id]
    await _save(db, project_id, notes)
    return notes


def format_notes(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return ""
    lines = "\n".join(f"- {n['text']}" for n in notes)
    return "## Project notes (written by the user; always follow them)\n" + lines


async def project_id_for_chat(
    db: AsyncSession, session_id: str, repo_path: str
) -> int | None:
    """The project a chat belongs to: its record, else the project whose
    folder the chat works in."""
    from sqlalchemy import or_, select

    from app.db.models import ChatSessionRecord, Project, Repo

    rec = await db.get(ChatSessionRecord, session_id)
    if rec is not None and rec.project_id:
        return int(rec.project_id)
    row = (
        await db.execute(
            select(Project.id)
            .outerjoin(Repo, Repo.id == Project.repo_id)
            .where(or_(Project.local_path == repo_path, Repo.local_path == repo_path))
            .limit(1)
        )
    ).first()
    return int(row[0]) if row else None
