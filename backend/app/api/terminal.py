"""Real interactive PTY terminal — Q12 (2026-09-24, GRIDIRON_PARTIAL "Real
interactive PTY terminal").

WebSocket endpoint over app.tools.execution.pty_session.PtySession — the
genuine bidirectional counterpart to app.api.chat's SSE stream. SSE is
one-directional (server -> client only), which is why every existing
bash-shaped tool is request/response; a real interactive terminal needs a
human's keystrokes (including Ctrl+C and window resizes) to reach a live
shell mid-command, which only a real WebSocket can carry.

Wire protocol (client -> server, one JSON object per text frame):
  {"type": "input", "data": "<raw bytes to write to the pty, base64>"}
  {"type": "resize", "rows": N, "cols": N}
  {"type": "ctrl_c"}

Wire protocol (server -> client):
  {"type": "ready", "pty_session_id": "...", "container_name": "..."}
  {"type": "output", "data": "<raw bytes from the pty, base64>"}
  {"type": "exited", "alive": false}
  {"type": "error", "message": "..."}

Output is base64-encoded because a real shell's stdout is arbitrary bytes
(control sequences, non-UTF-8 tool output) — text WebSocket frames must be
valid Unicode, so raw bytes cannot be sent as-is.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session_factory
from app.models.chat import ChatSession, get_session
from app.tools.execution.pty_session import PtySession, PtySessionUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

# Close codes in the 4000-4999 private-use range (RFC 6455 §7.4.2) — chosen
# to be individually distinguishable by the frontend, mirroring how the rest
# of this API returns distinct HTTP status codes rather than one generic
# failure.
_CLOSE_FEATURE_DISABLED = 4404
_CLOSE_SESSION_NOT_FOUND = 4004
_CLOSE_UNAUTHORIZED = 4403
_CLOSE_SANDBOX_UNAVAILABLE = 4503


async def _authenticate_as_approver(
    websocket: WebSocket, db: AsyncSession
) -> str | None:
    """WebSocket counterpart to app.middleware.rbac.require_approver — that
    function's own signature takes a `Request`, which FastAPI's dependency
    injection cannot substitute a `WebSocket` for, so this mirrors its exact
    same JWT / legacy-header / X-User-Id resolution tiers against
    `websocket.headers`/`websocket.cookies` instead, reusing the same
    underlying JWT decode and role-lookup functions rather than
    re-implementing any of the actual verification. Returns the resolved
    user id, or None if unauthorized (caller closes the connection — a
    WebSocket has no HTTPException equivalent to raise)."""
    settings = get_settings()
    if not settings.rbac_enabled:
        return "system"

    if settings.jwt_auth_enabled:
        auth_header = websocket.headers.get("Authorization", "")
        token = (
            auth_header[len("Bearer ") :]
            if auth_header.startswith("Bearer ")
            else websocket.cookies.get("gridiron_token")
        )
        if not token:
            return None
        try:
            from app.auth.jwt import decode_access_token
            from app.auth.revocation import current_role

            payload = decode_access_token(token)
            role = str(payload.get("role", "viewer"))
            username = str(payload.get("sub", "unknown"))
            live_role = await current_role(username, role, db)
            if live_role is None or live_role not in ("approver", "admin"):
                return None
            return username
        except Exception:
            logger.debug("terminal websocket auth: invalid token", exc_info=True)
            return None

    if settings.allow_legacy_role_header:
        x_user_role = websocket.headers.get("X-User-Role", "")
        x_user_id = websocket.headers.get("X-User-Id")
        if x_user_role.lower() in ("approver", "admin"):
            return x_user_id or x_user_role

    x_user_id = websocket.headers.get("X-User-Id")
    if x_user_id:
        from app.middleware.rbac import _get_user_role

        role = await _get_user_role(x_user_id, db)
        if role in ("approver", "admin"):
            return x_user_id

    return None


async def _pump_pty_to_websocket(pty: PtySession, websocket: WebSocket) -> None:
    """Background task: continuously drains the pty's real output and
    forwards it as it arrives — the live-streaming half of this endpoint.
    PtySession.read() is a blocking syscall (select+os.read), so it runs in
    a worker thread via asyncio.to_thread rather than blocking the event
    loop that also has to service the client's inbound control messages."""
    while True:
        chunk = await asyncio.to_thread(pty.read, 0.2)
        if chunk is None:
            continue
        if chunk == b"":
            await websocket.send_json({"type": "exited", "alive": False})
            return
        await websocket.send_json(
            {"type": "output", "data": base64.b64encode(chunk).decode("ascii")}
        )


@router.websocket("/ws/{chat_session_id}")
async def terminal_websocket(websocket: WebSocket, chat_session_id: str) -> None:
    settings = get_settings()

    async def refuse(code: int, reason: str) -> None:
        # Accept first, then close with the specific code: a WebSocket closed
        # BEFORE accept reaches the browser as a bare HTTP 403 / close code
        # 1006, so the UI could never tell "terminal disabled" from "not
        # allowed" from "session gone" (it showed "Connection closed (code
        # 1006)" for all three). Nothing is sent before the close.
        await websocket.accept()
        await websocket.close(code=code, reason=reason)

    if not settings.pty_terminal_enabled:
        await refuse(_CLOSE_FEATURE_DISABLED, "pty_terminal_enabled is False")
        return

    chat_session: ChatSession | None = get_session(chat_session_id)
    if chat_session is None:
        await refuse(_CLOSE_SESSION_NOT_FOUND, "Chat session not found")
        return

    factory = get_session_factory()
    async with factory() as db:
        user_id = await _authenticate_as_approver(websocket, db)
    if user_id is None:
        await refuse(_CLOSE_UNAUTHORIZED, "Approver role required")
        return

    await websocket.accept()

    pty = PtySession(
        cwd=chat_session.repo_path,
        image=settings.pty_terminal_image,
        network=settings.pty_terminal_network,
    )
    try:
        pty.start()
    except PtySessionUnavailableError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=_CLOSE_SANDBOX_UNAVAILABLE)
        return

    from app.fleet.audit_log import get_audit_log

    get_audit_log().append(
        action_type="pty_terminal_open",
        agent_name=user_id,
        description=f"Opened interactive PTY terminal for chat session {chat_session_id}",
        details={
            "chat_session_id": chat_session_id,
            "pty_session_id": pty.session_id,
            "container": pty.container_name,
            "cwd": pty.cwd,
        },
    )

    await websocket.send_json(
        {
            "type": "ready",
            "pty_session_id": pty.session_id,
            "container_name": pty.container_name,
        }
    )
    pump_task = asyncio.create_task(_pump_pty_to_websocket(pty, websocket))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "message": "invalid JSON control message"}
                )
                continue

            msg_type = msg.get("type")
            if msg_type == "input":
                data_b64 = msg.get("data", "")
                try:
                    pty.write(base64.b64decode(data_b64))
                except Exception:
                    await websocket.send_json(
                        {"type": "error", "message": "invalid base64 input data"}
                    )
            elif msg_type == "resize":
                rows = int(msg.get("rows", 24))
                cols = int(msg.get("cols", 80))
                pty.resize(rows, cols)
            elif msg_type == "ctrl_c":
                pty.send_ctrl_c()
            else:
                await websocket.send_json(
                    {"type": "error", "message": f"unknown message type {msg_type!r}"}
                )
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except (asyncio.CancelledError, Exception):
            pass
        # Off the event loop (docker kill + wait can take seconds), shielded
        # so a cancelled handler (client gone) still finishes the kill.
        close_task = asyncio.ensure_future(asyncio.to_thread(pty.close))
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await asyncio.wait({close_task}, timeout=20)
            raise
        get_audit_log().append(
            action_type="pty_terminal_close",
            agent_name=user_id,
            description=f"Closed interactive PTY terminal for chat session {chat_session_id}",
            details={
                "chat_session_id": chat_session_id,
                "pty_session_id": pty.session_id,
                "container": pty.container_name,
            },
        )
