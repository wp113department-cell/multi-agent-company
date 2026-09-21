"""Verification batch B3, item #253 (structured error reporting): the 422 handler returned
str(exc), which appends an endpoint-context stack frame with absolute SERVER FILE PATHS
to the response body (proved live). Only loc/msg/type are returned now."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_validation_errors_are_structured_and_leak_no_internals(client) -> None:
    r = client.post("/api/tasks/1/run", json={"mode": {"not": "a string"}})
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == "422"
    raw = r.text
    for leak in (
        'File "',
        "/home/",
        "site-packages",
        '.py"',
        "Traceback",
        "extension.py",
    ):
        assert leak not in raw, f"internal detail leaked: {leak!r}"
    d = body["error"]["details"]
    assert d and set(d[0]) == {"loc", "msg", "type"} and d[0]["loc"][0] == "body"
    assert "validation error" in body["error"]["message"]


def test_missing_body_is_reported_as_a_field_error_not_a_stack_frame(client) -> None:
    r = client.post("/api/tasks", json={})
    assert r.status_code == 422
    fields = {".".join(x["loc"]) for x in r.json()["error"]["details"]}
    assert {"body.title", "body.description"} <= fields
    assert "slowapi" not in r.text and "line " not in r.text.lower().replace(
        "field", ""
    )


def test_http_errors_keep_the_same_envelope(client) -> None:
    r = client.get("/api/tasks/999999999")
    assert r.status_code == 404 and set(r.json()) == {"error"}
    assert r.json()["error"]["code"] == "404"
