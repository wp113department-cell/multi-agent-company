"""C1 — attachments in chat (2026-10-09).

A chat message could only carry text. Now files can be attached: pictures
go to the model as images (so it can look at a screenshot), PDFs and
text/code files become text in the message. Size and type limits are
enforced, and stored history keeps a note instead of the picture data.
No AI runs here: a fake agent records what it would have received.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.chat import ChatAttachment, _prepare_attachments, _without_image_data
from app.main import app

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def _att(name: str, media: str, raw: bytes) -> ChatAttachment:
    return ChatAttachment(name=name, media_type=media, data=base64.b64encode(raw).decode())


def test_an_image_becomes_a_picture_for_the_model() -> None:
    text, images = _prepare_attachments(
        [ChatAttachment(name="shot.png", media_type="image/png", data=PNG)]
    )
    assert text == ""
    assert images == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}
    ]


def test_a_code_file_becomes_text_in_the_message() -> None:
    text, images = _prepare_attachments([_att("app.py", "text/x-python", b"print('hi')\n")])
    assert images == []
    assert "--- Attached file: app.py ---" in text and "print('hi')" in text


def test_an_unreadable_pdf_is_reported_not_crashed() -> None:
    text, _ = _prepare_attachments([_att("spec.pdf", "application/pdf", b"not a pdf")])
    assert "--- Attached PDF: spec.pdf ---" in text and "Could not extract" in text


@pytest.mark.parametrize(
    ("att", "why"),
    [
        (ChatAttachment(name="x.png", media_type="image/png", data="%%%"), "could not be read"),
        (_att("big.png", "image/png", b"0" * (5 * 1024 * 1024 + 1)), "larger than 5 MB"),
        (_att("big.log", "text/plain", b"a" * (300 * 1024 + 1)), "larger than 300 KB"),
        (_att("tool.exe", "application/octet-stream", b"MZ\x00\x00"), "not a text file"),
    ],
)
def test_limits_are_enforced(att: ChatAttachment, why: str) -> None:
    with pytest.raises(HTTPException) as err:
        _prepare_attachments([att])
    assert err.value.status_code == 400 and why in str(err.value.detail)


def test_stored_history_keeps_a_note_not_the_picture() -> None:
    content = [
        {"type": "text", "text": "what is wrong here?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}},
    ]
    stored = _without_image_data(content)
    assert stored[1] == {"type": "text", "text": "[an image was attached]"}
    assert PNG not in str(stored)
    assert _without_image_data("plain text") == "plain text"


# -- wiring: POST /api/chat/sessions/{id}/messages ----------------------------


class _FakeAgent:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.calls: list[tuple[str, Any]] = []

    async def run(self, user_message: str, images: Any = None) -> None:
        self.calls.append((user_message, images))
        content: Any = user_message
        if images:
            content = [{"type": "text", "text": user_message}, *images]
        self.session.history.append({"role": "user", "content": content})
        self.session.history.append({"role": "assistant", "content": "seen"})
        await self.session.push({"type": "done"})
        self.session.active = False


def test_sending_with_attachments_reaches_the_agent(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents import chat_agent

    agents: list[_FakeAgent] = []

    def fake_get(session: Any) -> _FakeAgent:
        agent = _FakeAgent(session)
        agents.append(agent)
        return agent

    monkeypatch.setattr(chat_agent, "get_or_create_chat_agent", fake_get)
    with TestClient(app) as client:
        sid = client.post("/api/chat/sessions", json={"repo_path": str(tmp_path)}).json()[
            "session_id"
        ]
        try:
            with client.stream(
                "POST",
                f"/api/chat/sessions/{sid}/messages",
                json={
                    "message": "Why does this fail?",
                    "attachments": [
                        {"name": "shot.png", "media_type": "image/png", "data": PNG},
                        {
                            "name": "err.log",
                            "media_type": "text/plain",
                            "data": base64.b64encode(b"Traceback: boom").decode(),
                        },
                    ],
                },
            ) as r:
                assert r.status_code == 200
                for _ in r.iter_lines():
                    pass
            history = client.get(f"/api/chat/sessions/{sid}/history").json()["history"]
        finally:
            client.delete(f"/api/chat/history/{sid}")
    message, images = agents[0].calls[0]
    assert message.startswith("Why does this fail?") and "Traceback: boom" in message
    assert images[0]["source"]["data"] == PNG
    assert any("Why does this fail?" in m["content"] for m in history)


def test_an_empty_message_without_files_is_refused(tmp_path: Any) -> None:
    with TestClient(app) as client:
        sid = client.post("/api/chat/sessions", json={"repo_path": str(tmp_path)}).json()[
            "session_id"
        ]
        try:
            r = client.post(f"/api/chat/sessions/{sid}/messages", json={"message": "  "})
            assert r.status_code == 400
        finally:
            client.delete(f"/api/chat/history/{sid}")


def test_the_stored_message_has_no_picture_data(tmp_path: Any) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.chat import _persist_new_messages
    from app.config import get_settings
    from app.models.chat import create_session, delete_session

    session = create_session(repo_path=str(tmp_path))
    session.history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}},
            ],
        }
    ]

    async def go() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            await _persist_new_messages(session, 0, factory)
            async with factory() as s:
                row = (
                    await s.execute(
                        text("SELECT content FROM chat_messages WHERE session_id = :s"),
                        {"s": session.session_id},
                    )
                ).scalar_one()
                await s.execute(
                    text("DELETE FROM chat_messages WHERE session_id = :s"),
                    {"s": session.session_id},
                )
                await s.commit()
                return str(row)
        finally:
            await engine.dispose()

    stored = asyncio.run(go())
    delete_session(session.session_id)
    assert PNG not in stored and "an image was attached" in stored
