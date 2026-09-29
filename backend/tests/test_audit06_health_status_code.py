"""Production audit 06 (2026-09-29): /health must return 503 when degraded.

It answered 200 with {"status": "degraded"} when the database was unreachable
(proved by stopping the real Postgres container mid-run), so `curl -f /health`
(docker-compose healthcheck), load balancers and uptime monitors never saw
the outage. Body is unchanged; only the status code.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_health_ok_is_200() -> None:
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_degraded_is_503_with_same_body() -> None:
    with TestClient(app) as c:

        def _broken_factory() -> object:
            raise ConnectionRefusedError("db down")

        with patch("app.db.session.get_session_factory", _broken_factory):
            r = c.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    assert "agents" in body
