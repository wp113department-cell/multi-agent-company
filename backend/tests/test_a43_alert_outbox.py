"""Sol A43 (2026-10-16): alerts survive an outage of the receiving service.

Before: an alert was one POST; if the webhook was down the alert was lost.
Now it is stored in alert_outbox, retried by deliver_due_alerts() until it
is delivered or, after ALERT_MAX_ATTEMPTS, kept as a dead letter. Every
attempt carries the same event id (the receiver drops repeats) and, with
ALERT_WEBHOOK_SECRET, an HMAC signature over timestamp and body.

Real Postgres and a real local HTTP server that can be switched to fail.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from app.config import get_settings
from app.db.session import new_isolated_async_engine
from app.services import alert


class _Hook(http.server.BaseHTTPRequestHandler):
    received: list[tuple[dict[str, str], bytes]] = []
    fail = False

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if _Hook.fail:
            self.send_response(503)
        else:
            _Hook.received.append((dict(self.headers), body))
            self.send_response(200)
        self.end_headers()

    def log_message(self, *_a: Any) -> None:
        pass


def _mine(task_id: int) -> list[tuple[dict[str, str], bytes]]:
    """Alerts this test raised (a retry also sends other tests' leftovers)."""
    return [r for r in _Hook.received if json.loads(r[1]).get("task_id") == task_id]


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import AsyncSession

    async def run():  # type: ignore[no-untyped-def]
        engine = new_isolated_async_engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s:
                result = await fn(s)
                await s.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _rows(task_id: int) -> list[Any]:
    from app.db.models import AlertOutbox

    async def q(s):  # type: ignore[no-untyped-def]
        rows = (await s.execute(select(AlertOutbox).order_by(AlertOutbox.id))).scalars()
        return [r for r in rows if r.payload.get("task_id") == task_id]

    return _db(q)  # type: ignore[no-any-return]


def _make_due(task_id: int) -> None:
    from app.db.models import AlertOutbox

    async def q(s):  # type: ignore[no-untyped-def]
        await s.execute(
            update(AlertOutbox)
            .where(AlertOutbox.payload["task_id"].as_integer() == task_id)
            .values(next_attempt_at=AlertOutbox.created_at)
        )

    _db(q)


def _retry() -> int:
    """deliver_due_alerts() uses the app's shared engine; give it a fresh
    one for this event loop."""
    import app.db.session as session

    async def run() -> int:
        session._engine = None
        session._session_factory = None
        try:
            return await alert.deliver_due_alerts()
        finally:
            await session.get_engine().dispose()
            session._engine = None
            session._session_factory = None

    return asyncio.run(run())


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """A webhook receiver; yields a task id unique to this test."""
    import random

    from app.db.models import AlertOutbox

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Hook.received = []
    _Hook.fail = False
    settings = get_settings()
    monkeypatch.setattr(
        settings, "alert_webhook_url", f"http://127.0.0.1:{srv.server_address[1]}/hook"
    )
    monkeypatch.setattr(settings, "alert_on_blocked", True)
    monkeypatch.setattr(settings, "alert_webhook_secret", "")
    monkeypatch.setattr(settings, "alert_max_attempts", 3)
    task_id = random.randint(10**8, 10**9)
    yield task_id
    srv.shutdown()

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(
            delete(AlertOutbox).where(
                AlertOutbox.payload["task_id"].as_integer() == task_id
            )
        )

    _db(clean)


def test_an_alert_raised_during_an_outage_is_delivered_after_it(hook: int) -> None:
    _Hook.fail = True
    asyncio.run(alert.send_task_alert(hook, "failed", "agent crashed"))
    [row] = _rows(hook)
    assert (
        row.status == "pending" and row.attempts == 1 and row.last_error == "HTTP 503"
    )
    assert _mine(hook) == []

    _Hook.fail = False
    _make_due(hook)
    assert _retry() >= 1
    [row] = _rows(hook)
    assert row.status == "sent" and row.attempts == 2
    [(headers, body)] = _mine(hook)
    assert json.loads(body)["detail"] == "agent crashed"
    # the receiver can drop a repeat by this id
    assert (
        headers["X-Gridiron-Event-Id"] == row.event_id == json.loads(body)["event_id"]
    )


def test_an_alert_that_never_gets_through_becomes_a_dead_letter(hook: int) -> None:
    _Hook.fail = True
    asyncio.run(alert.send_task_alert(hook, "failed", "still down"))
    for _ in range(2):
        _make_due(hook)
        _retry()
    [row] = _rows(hook)
    assert row.status == "dead" and row.attempts == 3
    _make_due(hook)
    _retry()
    assert _rows(hook)[0].attempts == 3  # dead letters are not retried


def test_the_same_alert_is_queued_once_while_undelivered(hook: int) -> None:
    _Hook.fail = True
    asyncio.run(alert.send_task_alert(hook, "blocked", "waiting on #1"))
    asyncio.run(alert.send_task_alert(hook, "blocked", "waiting on #1"))
    asyncio.run(alert.send_task_alert(hook, "blocked", "waiting on #2"))
    assert len(_rows(hook)) == 2


def test_alerts_are_signed_when_a_secret_is_set(
    hook: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import hmac

    monkeypatch.setattr(get_settings(), "alert_webhook_secret", "s3cret")
    asyncio.run(alert.send_task_alert(hook, "failed", "signed"))
    [(headers, body)] = _mine(hook)
    expected = hmac.new(
        b"s3cret",
        headers["X-Gridiron-Timestamp"].encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Gridiron-Signature"] == f"sha256={expected}"


def test_unsigned_without_a_secret(hook: int) -> None:
    asyncio.run(alert.send_task_alert(hook, "failed", "unsigned"))
    [(headers, _body)] = _mine(hook)
    assert "X-Gridiron-Signature" not in headers


def test_without_the_database_the_alert_is_still_sent_once(
    hook: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.db.session as session

    def broken() -> Any:
        raise RuntimeError("database is down")

    monkeypatch.setattr(session, "new_isolated_async_engine", broken)
    asyncio.run(alert.send_task_alert(hook, "failed", "db down"))
    assert len(_mine(hook)) == 1
