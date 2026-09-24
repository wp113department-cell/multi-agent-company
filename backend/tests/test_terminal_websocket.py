"""Q12 (2026-09-24, "Real interactive PTY terminal") —
app.api.terminal's WebSocket endpoint.

Real proof, not mocked: uses Starlette's real WebSocket test client against
the real FastAPI app, a real chat session, and (for the round-trip test) a
real Docker-sandboxed pty via the actual PtySession primitive whose own
mechanism (Ctrl+C, resize, sandbox containment) is already proven directly
in tests/test_pty_session.py — this file proves the WEBSOCKET WIRING on top
of it: feature-flag gating, chat-session resolution, auth, the real
input/output round trip, and cleanup on disconnect.
"""

from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.main import app
from app.models.chat import create_session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _feature_flag_on(monkeypatch: pytest.MonkeyPatch):
    """Every test in this file except the explicit "disabled" test needs
    the flag on — matching this project's own feature-flag-first rollout
    discipline (the flag defaults False in production)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "pty_terminal_enabled", True)


def test_rejects_when_feature_flag_disabled(client: TestClient, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "pty_terminal_enabled", False)
    session = create_session(repo_path=str(tmp_path))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/terminal/ws/{session.session_id}"):
            pass
    assert exc_info.value.code == 4404


def test_rejects_unknown_chat_session(client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/terminal/ws/no-such-session-id"):
            pass
    assert exc_info.value.code == 4004


def test_rejects_unauthorized_caller_when_rbac_enabled(
    client: TestClient, monkeypatch, tmp_path
):
    settings = get_settings()
    monkeypatch.setattr(settings, "rbac_enabled", True)
    monkeypatch.setattr(settings, "jwt_auth_enabled", False)
    monkeypatch.setattr(settings, "allow_legacy_role_header", False)
    session = create_session(repo_path=str(tmp_path))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/terminal/ws/{session.session_id}"):
            pass
    assert exc_info.value.code == 4403


def test_accepts_legacy_approver_header_when_rbac_enabled(
    client: TestClient, monkeypatch, tmp_path
):
    settings = get_settings()
    monkeypatch.setattr(settings, "rbac_enabled", True)
    monkeypatch.setattr(settings, "jwt_auth_enabled", False)
    monkeypatch.setattr(settings, "allow_legacy_role_header", True)
    session = create_session(repo_path=str(tmp_path))
    with client.websocket_connect(
        f"/api/terminal/ws/{session.session_id}",
        headers={"X-User-Role": "approver"},
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"


def test_real_input_output_round_trip(client: TestClient, tmp_path):
    session = create_session(repo_path=str(tmp_path))
    with client.websocket_connect(f"/api/terminal/ws/{session.session_id}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert "pty_session_id" in ready

        command = b"echo REAL_WS_ROUNDTRIP\n"
        ws.send_json({"type": "input", "data": base64.b64encode(command).decode()})

        collected = ""
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and "REAL_WS_ROUNDTRIP" not in collected:
            event = ws.receive_json()
            if event["type"] == "output":
                collected += base64.b64decode(event["data"]).decode(errors="replace")
        assert "REAL_WS_ROUNDTRIP" in collected


def test_ctrl_c_message_interrupts_a_running_command(client: TestClient, tmp_path):
    session = create_session(repo_path=str(tmp_path))
    with client.websocket_connect(f"/api/terminal/ws/{session.session_id}") as ws:
        ws.receive_json()  # ready

        ws.send_json(
            {"type": "input", "data": base64.b64encode(b"sleep 30\n").decode()}
        )
        time.sleep(0.5)
        ws.send_json({"type": "ctrl_c"})
        ws.send_json(
            {
                "type": "input",
                "data": base64.b64encode(b"echo BACK_AFTER_CTRLC\n").decode(),
            }
        )

        collected = ""
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and "BACK_AFTER_CTRLC" not in collected:
            event = ws.receive_json()
            if event["type"] == "output":
                collected += base64.b64decode(event["data"]).decode(errors="replace")
        assert "BACK_AFTER_CTRLC" in collected
        assert "^C" in collected


def test_disconnect_stops_the_container(client: TestClient, tmp_path):
    import os

    session = create_session(repo_path=str(tmp_path))
    with client.websocket_connect(f"/api/terminal/ws/{session.session_id}") as ws:
        ready = ws.receive_json()
        container_name = ready["container_name"]

    # The server-side handler processes the disconnect asynchronously —
    # there's no guarantee it has already run its cleanup `finally` block
    # (docker kill + wait, itself real wall-clock work) by the moment the
    # CLIENT's own `with` block returns, so poll rather than assert after a
    # single fixed sleep.
    deadline = time.monotonic() + 10.0
    result = ""
    while time.monotonic() < deadline:
        result = os.popen(
            f"docker ps --filter name={container_name} --format '{{{{.Names}}}}'"
        ).read()
        if container_name not in result:
            break
        time.sleep(0.5)
    assert container_name not in result
