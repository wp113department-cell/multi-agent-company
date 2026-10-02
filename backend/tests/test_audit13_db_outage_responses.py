"""Production audit 13 (2026-10-02): a database outage is reported as one.

Drill: Postgres stopped under a running app. Every DB-backed endpoint answered
a bare text/plain "Internal Server Error" and login said "Auth configuration
error". Now: 503 + Retry-After, JSON error shape. Other errors are not
misclassified as outages.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.errors import is_db_unavailable
from app.main import unhandled_exception_handler


def _real_connection_failure() -> BaseException:
    async def go() -> None:
        engine = create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/none")
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(go())
    except BaseException as exc:  # noqa: BLE001 — the failure is the point
        return exc
    raise AssertionError("connecting to port 1 unexpectedly succeeded")


def test_real_unreachable_database_is_classified_as_outage() -> None:
    assert is_db_unavailable(_real_connection_failure())


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError(2, "no such file"),
        ConnectionRefusedError(111, "refused"),
        asyncio.TimeoutError(),
        ValueError("bug"),
    ],
)
def test_non_database_errors_are_not_outages(exc: BaseException) -> None:
    assert not is_db_unavailable(exc)


def _app_raising(exc: BaseException) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_outage_returns_503_json_with_retry_after() -> None:
    r = _app_raising(_real_connection_failure()).get("/boom")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert r.json() == {
        "error": {"code": "503", "message": "Database unavailable, retry shortly"}
    }


def test_other_unhandled_errors_return_json_500_without_details() -> None:
    r = _app_raising(ValueError("secret internal detail")).get("/boom")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "500", "message": "Internal server error"}}
    assert "secret internal detail" not in r.text


def test_http_error_headers_reach_the_client() -> None:
    from fastapi import HTTPException

    from app.main import app as real_app

    probe = FastAPI()
    probe.add_exception_handler(
        HTTPException,
        real_app.exception_handlers[
            next(
                k
                for k in real_app.exception_handlers
                if getattr(k, "__name__", "") == "HTTPException"
            )
        ],
    )

    @probe.get("/x")
    async def x() -> None:
        raise HTTPException(
            503, "Database unavailable, retry shortly", headers={"Retry-After": "5"}
        )

    r = TestClient(probe).get("/x")
    assert r.status_code == 503 and r.headers.get("retry-after") == "5"
