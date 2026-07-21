"""Tests for RBAC middleware — viewer vs approver enforcement."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.middleware.rbac import require_approver

# ---- Helpers ----


def _make_db_mock(role: str | None) -> AsyncMock:
    """Return a mock AsyncSession that returns the given role from user_roles."""
    from app.db.models import UserRole

    db = AsyncMock()
    if role is not None:
        user_role_obj = MagicMock(spec=UserRole)
        user_role_obj.role = role
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = user_role_obj
    else:
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = (
            None  # user not in table → viewer
        )

    db.execute = AsyncMock(return_value=scalar_result)
    return db


def _make_request(x_user_role: str = "") -> MagicMock:
    """Return a mock Request with given headers."""
    req = MagicMock()
    req.headers = {"X-User-Role": x_user_role}
    return req


# ---- Tests: RBAC enabled (default) ----


@pytest.mark.asyncio
async def test_approver_role_passes() -> None:
    """User with approver role must not raise."""
    db = _make_db_mock("approver")
    req = _make_request()
    with patch("app.middleware.rbac.get_settings") as mock_settings:
        mock_settings.return_value.rbac_enabled = True
        mock_settings.return_value.jwt_auth_enabled = False
        result = await require_approver(request=req, x_user_id="alice", db=db)
    assert result == "alice"


@pytest.mark.asyncio
async def test_viewer_role_raises_403() -> None:
    """User with viewer role must raise 403."""
    db = _make_db_mock("viewer")
    req = _make_request()
    with patch("app.middleware.rbac.get_settings") as mock_settings:
        mock_settings.return_value.rbac_enabled = True
        mock_settings.return_value.jwt_auth_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            await require_approver(request=req, x_user_id="bob", db=db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_user_id_raises_403() -> None:
    """No X-User-Id header → 403."""
    db = _make_db_mock(None)
    req = _make_request()
    with patch("app.middleware.rbac.get_settings") as mock_settings:
        mock_settings.return_value.rbac_enabled = True
        mock_settings.return_value.jwt_auth_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            await require_approver(request=req, x_user_id=None, db=db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_user_not_in_table_defaults_to_viewer() -> None:
    """User not in user_roles → defaults to viewer → 403."""
    db = _make_db_mock(None)  # no row in table
    req = _make_request()
    with patch("app.middleware.rbac.get_settings") as mock_settings:
        mock_settings.return_value.rbac_enabled = True
        mock_settings.return_value.jwt_auth_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            await require_approver(request=req, x_user_id="charlie", db=db)
    assert exc_info.value.status_code == 403


# ---- Tests: RBAC disabled ----


@pytest.mark.asyncio
async def test_rbac_disabled_bypasses_check() -> None:
    """When RBAC_ENABLED=false, all requests treated as approver."""
    db = _make_db_mock("viewer")  # would normally fail
    req = _make_request()
    with patch("app.middleware.rbac.get_settings") as mock_settings:
        mock_settings.return_value.rbac_enabled = False
        result = await require_approver(request=req, x_user_id=None, db=db)
    assert result == "system"


@pytest.mark.asyncio
async def test_rbac_disabled_returns_user_id() -> None:
    """With RBAC_ENABLED=false, user_id from header is returned."""
    db = _make_db_mock("viewer")
    req = _make_request()
    with patch("app.middleware.rbac.get_settings") as mock_settings:
        mock_settings.return_value.rbac_enabled = False
        result = await require_approver(request=req, x_user_id="dave", db=db)
    assert result == "dave"
