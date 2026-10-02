"""Qoder cross-check PROD-08-102 (2026-10-02): a rate-limited request got
slowapi's {"error": "<string>"} body instead of the app's standard
{"error": {"code", "message"}} envelope, so the UI could not show it.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.responses import JSONResponse

from app.main import _rate_limit_handler


def test_429_uses_the_standard_error_envelope() -> None:
    class _Limiter:
        def _inject_headers(
            self, response: JSONResponse, _limit: object
        ) -> JSONResponse:
            response.headers["Retry-After"] = "60"
            return response

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(limiter=_Limiter())),
        state=SimpleNamespace(view_rate_limit=None),
    )
    exc = SimpleNamespace(detail="10 per 1 minute")
    response = _rate_limit_handler(request, exc)  # type: ignore[arg-type]
    assert response.status_code == 429
    body = response.body.decode()
    assert '"code":"429"' in body.replace(" ", "")
    assert "Too many requests" in body
    assert response.headers["retry-after"] == "60"
