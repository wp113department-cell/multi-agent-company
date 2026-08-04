"""Stage 3, Day 63 (PLAN.md) — "Remaining smaller NOT VERIFIED items
batched; final Stage 3 write-up in answers.md."

This file covers the one fix this batch produced (the rest of the batch was
verification-only — see `65days_plan/answers.md`'s new "Stage 3 Final
Write-Up" section for the full disposition of every item, and
`IMPLEMENTATION_PROGRESS.md`'s Day 63 entry for how each was checked):

`answers.md`'s own Appendix "Hidden Architectural Risk Audit" finding #11
("`GET /api/tasks/{id}/stream` has no authentication dependency, unlike its
stop/resume/tokens siblings in the same file") was re-checked against the
live code during this batch and found still real — `app/api/activity.py`'s
`stream_task_events` was the one endpoint in that file with no
`require_authenticated` dependency. Fixed by adding it. A naive version of
this fix would have broken the real frontend usage: `apps/web/app/
stream/[taskId]/page.tsx` connects via a browser-native `EventSource`, which
cannot set a custom `Authorization` header — so `app/middleware/rbac.py::
require_authenticated` was extended with a cookie fallback (the
`gridiron_token` cookie `lib/auth.ts::setToken()` already sets on every
login, originally only for `middleware.ts`'s server-side route gating,
which `EventSource` DOES send automatically for a same-origin request) —
strictly additive: every existing Bearer-header caller is checked first and
unaffected.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.middleware.rbac import require_authenticated


class TestCookieFallbackForJwtAuth:
    @pytest.mark.asyncio
    async def test_bearer_header_still_takes_priority_over_cookie(self) -> None:
        """Existing callers (fetch() with authHeaders()) are unaffected --
        proves the cookie branch is a fallback, not a header override."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer header-token"}
        req.cookies = {"gridiron_token": "cookie-token"}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = True
            with patch("app.auth.jwt.decode_access_token") as mock_decode:
                mock_decode.return_value = {"sub": "header-user"}
                result = await require_authenticated(request=req, x_user_id=None, db=db)
        assert result == "header-user"
        mock_decode.assert_called_once_with("header-token")

    @pytest.mark.asyncio
    async def test_cookie_accepted_when_no_authorization_header_present(self) -> None:
        """The real fix: EventSource can't set a custom header, but DOES
        send the gridiron_token cookie same-origin -- this must now pass."""
        req = MagicMock()
        req.headers = {}
        req.cookies = {"gridiron_token": "cookie-token"}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = True
            with patch("app.auth.jwt.decode_access_token") as mock_decode:
                mock_decode.return_value = {"sub": "cookie-user"}
                result = await require_authenticated(request=req, x_user_id=None, db=db)
        assert result == "cookie-user"
        mock_decode.assert_called_once_with("cookie-token")

    @pytest.mark.asyncio
    async def test_no_header_and_no_cookie_still_401s(self) -> None:
        """The gap this whole fix closes must not silently become 'no auth
        required at all' -- absence of both credentials still fails."""
        req = MagicMock()
        req.headers = {}
        req.cookies = {}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = True
            with pytest.raises(HTTPException) as exc_info:
                await require_authenticated(request=req, x_user_id=None, db=db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_cookie_token_401s_same_as_invalid_header_token(
        self,
    ) -> None:
        req = MagicMock()
        req.headers = {}
        req.cookies = {"gridiron_token": "garbage"}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = True
            with patch(
                "app.auth.jwt.decode_access_token", side_effect=ValueError("bad token")
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await require_authenticated(request=req, x_user_id=None, db=db)
        assert exc_info.value.status_code == 401


def test_stream_endpoint_now_requires_authentication() -> None:
    """Appendix finding #11: stream_task_events was the one endpoint in
    activity.py without an auth dependency. Introspects the real route
    function's signature rather than invoking the (infinite-generator)
    StreamingResponse itself."""
    from app.api.activity import stream_task_events

    sig = inspect.signature(stream_task_events)
    assert "_actor" in sig.parameters
    default = sig.parameters["_actor"].default
    # FastAPI wraps Depends(require_authenticated) in a params.Depends object
    # whose .dependency is the real callable -- assert it's the real function,
    # not a stand-in.
    assert getattr(default, "dependency", None) is require_authenticated


def test_stream_endpoint_still_has_its_stop_resume_tokens_siblings_gated() -> None:
    """Regression guard: confirms this fix didn't accidentally *remove* auth
    from the siblings the Appendix finding compared it against."""
    from app.api.activity import get_token_usage, resume_task, stop_task

    for fn in (stop_task, resume_task):
        sig = inspect.signature(fn)
        assert "_actor" in sig.parameters
        assert (
            getattr(sig.parameters["_actor"].default, "dependency", None)
            is require_authenticated
        )
    # get_token_usage was never gated by the Appendix finding and is left
    # unchanged by this fix -- documented here, not silently assumed.
    assert "_actor" not in inspect.signature(get_token_usage).parameters
