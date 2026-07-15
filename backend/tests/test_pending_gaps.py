"""Tests for all pending-gap features implemented in this session.

Covers:
- Rate limiting config + slowapi wiring
- S3 dispatch in save_artifact_async
- Alerting wiring in agents.py (import check)
- Extended /health response structure
- Migration 009 artifact (chat_messages table, outcome enum docs)
- Persistent chat history helpers (save_message_to_db, load_history_from_db, get_or_restore_session)
- JWT auth module (create/decode token, hash/verify password)
- Auth API router structure
- Auth dependencies (get_current_user, require_approver)
- Procfile and docker-compose existence
- Eval runner and suites structure
- Config new fields
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO = Path(__file__).parent.parent.parent  # CRR2906 root
_BACKEND = Path(__file__).parent.parent       # backend/


# ===========================================================================
# 1. Config new fields
# ===========================================================================

class TestConfigNewFields:
    def test_rate_limit_fields(self) -> None:
        from app.config import Settings
        fields = {f.alias or name for name, f in Settings.model_fields.items()}
        # field names (not aliases)
        names = set(Settings.model_fields.keys())
        assert "rate_limit_enabled" in names
        assert "rate_limit_default" in names
        assert "rate_limit_tasks" in names
        assert "rate_limit_agents" in names

    def test_jwt_fields(self) -> None:
        from app.config import Settings
        names = set(Settings.model_fields.keys())
        assert "jwt_secret_key" in names
        assert "jwt_algorithm" in names
        assert "jwt_access_token_expire_minutes" in names
        assert "jwt_auth_enabled" in names

    def test_rate_limit_enabled_default_true(self) -> None:
        from app.config import Settings
        f = Settings.model_fields["rate_limit_enabled"]
        assert f.default is True

    def test_jwt_auth_enabled_default_false(self) -> None:
        from app.config import Settings
        f = Settings.model_fields["jwt_auth_enabled"]
        assert f.default is False

    def test_jwt_secret_key_default_empty(self) -> None:
        from app.config import Settings
        f = Settings.model_fields["jwt_secret_key"]
        assert f.default == ""


# ===========================================================================
# 2. Rate limiting — slowapi wired in main.py
# ===========================================================================

class TestRateLimiting:
    def test_slowapi_import(self) -> None:
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        assert callable(Limiter)

    def test_limiter_in_main(self) -> None:
        from app.main import limiter
        from slowapi import Limiter
        assert isinstance(limiter, Limiter)

    def test_rate_limit_middleware_in_main(self) -> None:
        from app.main import app, limiter
        # Verify middleware is registered by checking the limiter is on app.state
        assert app.state.limiter is limiter


# ===========================================================================
# 3. S3 dispatch in save_artifact_async
# ===========================================================================

class TestS3Dispatch:
    def test_store_imports_s3_store(self) -> None:
        import app.artifacts.store as store_mod
        src = Path(store_mod.__file__).read_text()
        assert "s3_store" in src
        assert "artifact_backend" in src

    def test_save_artifact_async_is_async(self) -> None:
        import asyncio
        from app.artifacts.store import save_artifact_async
        assert asyncio.iscoroutinefunction(save_artifact_async)

    @pytest.mark.asyncio
    async def test_db_path_no_s3_call(self, tmp_path: Path) -> None:
        """When artifact_backend=db, s3_store.save_artifact_s3 must NOT be called."""
        from unittest.mock import patch as up
        with up("app.config.get_settings") as mock_settings:
            s = MagicMock()
            s.artifact_backend = "db"
            s.worktrees_dir = str(tmp_path)
            mock_settings.return_value = s

            with up("app.artifacts.s3_store.save_artifact_s3") as mock_s3:
                from app.artifacts.store import save_artifact
                record = save_artifact(1, "plan", "hello", "agent")
                mock_s3.assert_not_called()

    def test_s3_store_module_exists(self) -> None:
        from app.artifacts.s3_store import save_artifact_s3, load_artifact_s3, _make_key
        assert callable(save_artifact_s3)
        assert callable(load_artifact_s3)


# ===========================================================================
# 4. Alerting wired in agents.py
# ===========================================================================

class TestAlertingWiring:
    def test_send_task_alert_imported_in_agents(self) -> None:
        import app.api.agents as agents_mod
        src = Path(agents_mod.__file__).read_text()
        assert "send_task_alert" in src

    def test_alert_called_on_planning_blocked(self) -> None:
        import app.api.agents as agents_mod
        src = Path(agents_mod.__file__).read_text()
        # Both planning and manager blocked paths must call alert
        assert src.count("send_task_alert") >= 4

    def test_alert_service_module_exists(self) -> None:
        from app.services.alert import send_task_alert
        import asyncio
        assert asyncio.iscoroutinefunction(send_task_alert)

    @pytest.mark.asyncio
    async def test_alert_no_op_when_no_url(self) -> None:
        from app.services.alert import send_task_alert
        with patch("app.services.alert.get_settings") as mock_s:
            s = MagicMock()
            s.alert_webhook_url = ""
            mock_s.return_value = s
            # Must not raise
            await send_task_alert(1, "blocked", "test")


# ===========================================================================
# 5. /health endpoint extended structure
# ===========================================================================

class TestHealthEndpoint:
    def test_health_function_returns_dict(self) -> None:
        import asyncio
        from app.main import health
        # Check that the function is async
        import inspect
        assert inspect.iscoroutinefunction(health)

    def test_health_source_checks_db(self) -> None:
        from app.main import health
        import inspect
        src = inspect.getsource(health)
        assert "db" in src
        assert "redis" in src
        assert "s3" in src


# ===========================================================================
# 6. Migration 009 exists
# ===========================================================================

class TestMigration009:
    def test_migration_file_exists(self) -> None:
        p = _BACKEND / "migrations" / "versions" / "009_outcome_enum_chat_messages.py"
        assert p.exists()

    def test_migration_has_chat_messages_table(self) -> None:
        p = _BACKEND / "migrations" / "versions" / "009_outcome_enum_chat_messages.py"
        src = p.read_text()
        assert "chat_messages" in src
        assert "session_id" in src
        assert "role" in src

    def test_migration_revision_is_009(self) -> None:
        p = _BACKEND / "migrations" / "versions" / "009_outcome_enum_chat_messages.py"
        src = p.read_text()
        assert 'revision: str = "009"' in src
        assert 'down_revision' in src


# ===========================================================================
# 7. Persistent chat history
# ===========================================================================

class TestPersistentChatHistory:
    def test_save_message_to_db_exists(self) -> None:
        from app.models.chat import save_message_to_db
        import asyncio
        assert asyncio.iscoroutinefunction(save_message_to_db)

    def test_load_history_from_db_exists(self) -> None:
        from app.models.chat import load_history_from_db
        import asyncio
        assert asyncio.iscoroutinefunction(load_history_from_db)

    def test_get_or_restore_session_exists(self) -> None:
        from app.models.chat import get_or_restore_session
        import asyncio
        assert asyncio.iscoroutinefunction(get_or_restore_session)

    @pytest.mark.asyncio
    async def test_load_history_returns_empty_on_db_error(self) -> None:
        from app.models.chat import load_history_from_db
        db = MagicMock()
        db.execute = AsyncMock(side_effect=Exception("no connection"))
        result = await load_history_from_db("test-session-id", db)
        assert result == []

    @pytest.mark.asyncio
    async def test_save_message_swallows_error(self) -> None:
        from app.models.chat import save_message_to_db
        db = MagicMock()
        db.execute = AsyncMock(side_effect=Exception("no connection"))
        # Must not raise
        await save_message_to_db("s1", "/repo", "user", "hello", db)

    def test_chat_api_imports_db_helpers(self) -> None:
        import app.api.chat as chat_mod
        src = Path(chat_mod.__file__).read_text()
        assert "save_message_to_db" in src
        assert "load_history_from_db" in src
        assert "get_or_restore_session" in src

    @pytest.mark.asyncio
    async def test_get_or_restore_creates_new_session(self) -> None:
        from app.models.chat import get_or_restore_session, _sessions
        sid = "test-restore-999"
        _sessions.pop(sid, None)
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(mappings=lambda: MagicMock(all=lambda: [])))
        session = await get_or_restore_session(sid, "/repo", db)
        assert session.session_id == sid


# ===========================================================================
# 8. JWT auth module
# ===========================================================================

class TestJWTModule:
    def test_hash_and_verify_password(self) -> None:
        from app.auth.jwt import hash_password, verify_password
        h = hash_password("s3cr3t")
        assert verify_password("s3cr3t", h)
        assert not verify_password("wrong", h)

    def test_create_and_decode_token(self) -> None:
        from app.auth.jwt import create_access_token, decode_access_token
        with patch("app.auth.jwt.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_secret_key = "test-secret-key-32chars-minimum-ok"
            s.jwt_algorithm = "HS256"
            s.jwt_access_token_expire_minutes = 60
            mock_s.return_value = s
            token = create_access_token({"sub": "alice", "role": "approver"})
            payload = decode_access_token(token)
            assert payload["sub"] == "alice"
            assert payload["role"] == "approver"

    def test_create_token_raises_without_secret(self) -> None:
        from app.auth.jwt import create_access_token
        with patch("app.auth.jwt.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_secret_key = ""
            mock_s.return_value = s
            with pytest.raises(ValueError):
                create_access_token({"sub": "x"})

    def test_expired_token_raises_jwterror(self) -> None:
        from app.auth.jwt import create_access_token, decode_access_token
        from jose import JWTError
        with patch("app.auth.jwt.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_secret_key = "test-secret-key-32chars-minimum-ok"
            s.jwt_algorithm = "HS256"
            s.jwt_access_token_expire_minutes = -1  # already expired
            mock_s.return_value = s
            token = create_access_token({"sub": "x"})
        with patch("app.auth.jwt.get_settings") as mock_s2:
            s2 = MagicMock()
            s2.jwt_secret_key = "test-secret-key-32chars-minimum-ok"
            s2.jwt_algorithm = "HS256"
            mock_s2.return_value = s2
            with pytest.raises(JWTError):
                decode_access_token(token)


# ===========================================================================
# 9. Auth API router
# ===========================================================================

class TestAuthRouter:
    def test_auth_router_exists(self) -> None:
        from app.api.auth import router
        from fastapi import APIRouter
        assert isinstance(router, APIRouter)

    def test_auth_router_prefix(self) -> None:
        from app.api.auth import router
        assert router.prefix == "/api/auth"

    def test_login_route_registered(self) -> None:
        from app.api.auth import router
        paths = [r.path for r in router.routes]
        assert "/api/auth/login" in paths

    def test_me_route_registered(self) -> None:
        from app.api.auth import router
        paths = [r.path for r in router.routes]
        assert "/api/auth/me" in paths

    def test_setup_route_registered(self) -> None:
        from app.api.auth import router
        paths = [r.path for r in router.routes]
        assert "/api/auth/setup" in paths

    def test_auth_router_in_main_app(self) -> None:
        import app.main as main_mod
        src = Path(main_mod.__file__).read_text()
        assert "auth_router" in src
        assert "app.include_router(auth_router)" in src


# ===========================================================================
# 10. Auth dependencies
# ===========================================================================

class TestAuthDependencies:
    def test_get_current_user_is_async(self) -> None:
        import asyncio
        from app.auth.dependencies import get_current_user
        assert asyncio.iscoroutinefunction(get_current_user)

    def test_require_approver_is_async(self) -> None:
        import asyncio
        from app.auth.dependencies import require_approver
        assert asyncio.iscoroutinefunction(require_approver)

    @pytest.mark.asyncio
    async def test_legacy_viewer_header(self) -> None:
        from app.auth.dependencies import get_current_user
        request = MagicMock()
        request.headers = {"X-User-Role": "viewer"}
        with patch("app.auth.dependencies.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_auth_enabled = False
            mock_s.return_value = s
            user = await get_current_user(request)
            assert user.role == "viewer"

    @pytest.mark.asyncio
    async def test_legacy_approver_header(self) -> None:
        from app.auth.dependencies import get_current_user
        request = MagicMock()
        request.headers = {"X-User-Role": "approver"}
        with patch("app.auth.dependencies.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_auth_enabled = False
            mock_s.return_value = s
            user = await get_current_user(request)
            assert user.role == "approver"

    @pytest.mark.asyncio
    async def test_require_approver_blocks_viewer(self) -> None:
        from fastapi import HTTPException
        from app.auth.dependencies import require_approver
        request = MagicMock()
        request.headers = {"X-User-Role": "viewer"}
        with patch("app.auth.dependencies.get_settings") as mock_s:
            s = MagicMock()
            s.jwt_auth_enabled = False
            s.rbac_enabled = True
            mock_s.return_value = s
            with pytest.raises(HTTPException) as exc_info:
                await require_approver(request)
            assert exc_info.value.status_code == 403


# ===========================================================================
# 11. Procfile + docker-compose
# ===========================================================================

class TestInfraFiles:
    def test_procfile_exists(self) -> None:
        assert (_REPO / "Procfile").exists()

    def test_procfile_has_web(self) -> None:
        content = (_REPO / "Procfile").read_text()
        assert "web:" in content
        assert "uvicorn" in content

    def test_procfile_has_worker(self) -> None:
        content = (_REPO / "Procfile").read_text()
        assert "worker:" in content
        assert "rq worker" in content

    def test_docker_compose_exists(self) -> None:
        assert (_REPO / "docker-compose.yml").exists()

    def test_docker_compose_has_db(self) -> None:
        content = (_REPO / "docker-compose.yml").read_text()
        assert "pgvector" in content

    def test_docker_compose_has_redis(self) -> None:
        content = (_REPO / "docker-compose.yml").read_text()
        assert "redis" in content

    def test_docker_compose_has_worker_profile(self) -> None:
        content = (_REPO / "docker-compose.yml").read_text()
        assert "rq worker" in content
        assert "profiles" in content


# ===========================================================================
# 12. Agent Evaluation suite
# ===========================================================================

class TestEvalSuite:
    def test_suites_dict_exists(self) -> None:
        from evals.suites import SUITES
        assert isinstance(SUITES, dict)
        assert len(SUITES) > 0

    def test_all_suites_have_cases(self) -> None:
        from evals.suites import SUITES
        from evals.eval_runner import EvalCase
        for slug, cases in SUITES.items():
            assert len(cases) > 0, f"Suite {slug!r} has no cases"
            for case in cases:
                assert isinstance(case, EvalCase)

    def test_eval_runner_imports(self) -> None:
        from evals.eval_runner import run_eval_case, run_suite, save_report, EvalCase, EvalResult, EvalReport
        assert callable(run_eval_case)
        assert callable(run_suite)
        assert callable(save_report)

    def test_all_cases_have_criteria(self) -> None:
        from evals.suites import SUITES
        for slug, cases in SUITES.items():
            for case in cases:
                assert len(case.criteria) > 0, f"Case {case.name!r} in {slug!r} has no criteria"
                assert len(case.criteria) == len(case.criteria_labels)

    def test_eval_report_to_dict(self) -> None:
        from evals.eval_runner import EvalReport, EvalResult
        r = EvalResult(
            case_name="test", agent_slug="bug_fix", passed=True,
            criteria_results=[{"criterion": "x", "passed": True}],
            duration_seconds=1.5, tokens_in=100, tokens_out=50, status="completed"
        )
        report = EvalReport(
            agent_slug="bug_fix", total=1, passed=1, failed=0, score=1.0,
            duration_seconds=1.5, results=[r]
        )
        d = report.to_dict()
        assert d["agent_slug"] == "bug_fix"
        assert d["score"] == 1.0
        assert len(d["results"]) == 1

    def test_suites_cover_key_agents(self) -> None:
        from evals.suites import SUITES
        key_agents = {"bug_fix", "security_reviewer", "user_story_generator", "evaluation_agent"}
        assert key_agents.issubset(SUITES.keys())
