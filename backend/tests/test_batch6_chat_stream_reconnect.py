"""AUDIT_Q_BATCH06 §9 "Reconnect logic" — the chat page's fetch-based POST
stream had no reconnect logic at all: a dropped connection just stopped,
even though the agent (app/api/chat.py::send_message -> _run_agent) already
runs as a background task fully decoupled from the originating HTTP
connection. GET /api/chat/sessions/{id}/stream (app/api/chat.py) closes that
gap — it re-subscribes to the same session._queue an in-progress turn is
still writing to, so the frontend can reconnect (EventSource, capped
exponential backoff — apps/web/app/chat/page.tsx) without re-sending the
user's message or re-running the agent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import create_session, delete_session


def test_stream_404_for_unknown_session() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/chat/sessions/does-not-exist/stream")
    assert resp.status_code == 404


def test_stream_409_when_session_not_active() -> None:
    session = create_session(repo_path="/tmp/does-not-matter")
    try:
        session.active = False
        with TestClient(app) as client:
            resp = client.get(f"/api/chat/sessions/{session.session_id}/stream")
        assert resp.status_code == 409
    finally:
        delete_session(session.session_id)


def test_stream_reattaches_to_active_session_and_delivers_queued_events() -> None:
    """The core reconnect contract: a turn already in flight (active=True,
    with events already pushed to its queue — exactly the state a dropped
    connection leaves behind) is deliverable to a *new* GET connection,
    proving reattachment doesn't require replaying the original POST."""
    session = create_session(repo_path="/tmp/does-not-matter")
    try:
        session.active = True
        session._queue.put_nowait({"type": "text_delta", "text": "hello"})
        session._queue.put_nowait({"type": "done"})

        with TestClient(app) as client:
            with client.stream(
                "GET", f"/api/chat/sessions/{session.session_id}/stream"
            ) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                body = ""
                for chunk in resp.iter_text():
                    body += chunk
                    if '"type": "done"' in body or '"type":"done"' in body:
                        break
        assert "text_delta" in body
        assert "hello" in body
        assert "done" in body
    finally:
        delete_session(session.session_id)
