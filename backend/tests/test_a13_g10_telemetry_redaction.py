"""Sol A13 + G10 (2026-10-09): nothing that leaves the platform carries a
secret — Sentry events, logs, alert webhooks — and alerts really fire.

Sentry's before_send used to return every event unchanged. Fake canary
secrets are planted as the platform's own settings, then pushed through a
REAL Sentry client (a transport captures exactly what would be sent), the
JSON log formatter and a real alert webhook (a local HTTP server).
"""

from __future__ import annotations

import asyncio
import http.server
import io
import json
import logging
import threading
from typing import Any

import pytest

from app.observability import redaction

API_KEY = "sk-ant-api03-CANARYcanaryCANARY0001"
JWT_SECRET = "jwt-canary-secret-value-0002"
DB_PASSWORD = "dbCanaryPassw0rd0003"
GH_TOKEN = "ghp_CANARYcanaryCANARYcanary0004xyz"
CANARIES = [API_KEY, JWT_SECRET, DB_PASSWORD, GH_TOKEN]


@pytest.fixture(autouse=True)
def canaries(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", API_KEY)
    monkeypatch.setattr(s, "jwt_secret_key", JWT_SECRET)
    monkeypatch.setattr(
        s, "database_url", f"postgresql+asyncpg://gridiron:{DB_PASSWORD}@db:5432/x"
    )
    monkeypatch.setattr(s, "github_token", GH_TOKEN)
    redaction.reset_cache()
    yield
    redaction.reset_cache()


def _clean(text: str) -> bool:
    return not any(c in text for c in CANARIES)


def test_text_and_structures_are_redacted() -> None:
    text = (
        f"key={API_KEY} jwt={JWT_SECRET} url=postgresql://u:{DB_PASSWORD}@h/db "
        f"Authorization: Bearer {GH_TOKEN} other=sk-ant-api03-somethingELSE123456"
    )
    out = redaction.redact_text(text)
    assert _clean(out) and "sk-ant-api03-somethingELSE" not in out
    data = {
        "headers": [["Authorization", "Bearer abc"], ["Accept", "text/html"]],
        "password": "hunter2-long-enough",
        "nested": {"tool_input": {"command": f"export KEY={API_KEY}"}},
        "items": [f"token {GH_TOKEN}"],
    }
    red = redaction.redact(data)
    assert red["headers"] == [["Authorization", "[REDACTED]"], ["Accept", "text/html"]]
    assert red["password"] == "[REDACTED]"
    assert _clean(json.dumps(red))
    assert data["password"] == "hunter2-long-enough"  # the original is untouched


def test_a_real_sentry_event_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.transport import Transport

    from app.config import get_settings
    from app.main import _init_sentry

    sent: list[str] = []

    class Capture(Transport):
        def capture_envelope(self, envelope: Any) -> None:
            buf = io.BytesIO()
            envelope.serialize_into(buf)
            sent.append(buf.getvalue().decode(errors="replace"))

    settings = get_settings()
    monkeypatch.setattr(settings, "sentry_dsn", "https://public@o0.ingest.sentry.io/0")
    real_init = sentry_sdk.init
    monkeypatch.setattr(
        sentry_sdk, "init", lambda *a, **k: real_init(*a, transport=Capture, **k)
    )
    try:
        _init_sentry(settings)
        sentry_sdk.add_breadcrumb(message=f"called the API with {API_KEY}")
        sentry_sdk.set_context("request", {"headers": {"Cookie": f"s={JWT_SECRET}"}})
        try:
            local_secret = GH_TOKEN  # noqa: F841 — captured as a frame variable
            raise RuntimeError(
                f"connect failed: postgresql://gridiron:{DB_PASSWORD}@db/x key={API_KEY}"
            )
        except RuntimeError as exc:
            sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=5)
    finally:
        real_init()  # back to no Sentry for the rest of the suite
    assert sent, "Sentry sent nothing"
    payload = "\n".join(sent)
    assert "connect failed" in payload
    assert _clean(payload), "a canary secret reached Sentry"


def test_log_lines_are_redacted() -> None:
    from app.observability.logging_context import JsonLogFormatter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonLogFormatter())
    log = logging.getLogger("a13-test")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.warning("calling the API with %s", API_KEY)
        try:
            raise ValueError(f"bad token {GH_TOKEN}")
        except ValueError:
            log.exception("failed with db %s", DB_PASSWORD)
    finally:
        log.removeHandler(handler)
    out = buf.getvalue()
    assert "calling the API" in out and _clean(out)


class _Hook(http.server.BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []

    def log_message(self, *a: Any) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        _Hook.received.append(json.loads(self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()


def test_a_blocked_task_alert_fires_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.services.alert import send_task_alert

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Hook.received.clear()
    settings = get_settings()
    monkeypatch.setattr(
        settings, "alert_webhook_url", f"http://127.0.0.1:{srv.server_address[1]}/hook"
    )
    monkeypatch.setattr(settings, "alert_on_blocked", True)
    try:
        asyncio.run(
            send_task_alert(
                42,
                "blocked",
                f"Pipeline blocked: auth failed for key {API_KEY}",
                extra={"env": {"GITHUB_TOKEN": GH_TOKEN}},
            )
        )
    finally:
        srv.shutdown()
    assert len(_Hook.received) == 1, "the alert did not fire"
    body = json.dumps(_Hook.received[0])
    assert "Pipeline blocked" in body and _clean(body)
