"""Tests for AUDIT_Q_BATCH15 §110/§111 gap-closure — PromptRegistry.rollback()
finally gets a real caller: GET /api/fleet/prompts/{role_name}/history and
POST /api/fleet/prompts/{role_name}/rollback (app/api/fleet_dashboard.py).

Uses app.main.app (the real app) with require_approver overridden — standard
practice in this test suite for RBAC-gated routes (see
test_batch11_privacy_api.py) — while PromptRegistry itself talks to the real
dev database and writes/cleans up a real (fake, td_ prefixed) roles/*.md file,
mirroring test_prompt_registry.py's own established convention.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.fleet.prompt_registry import PromptRegistry, _role_file_path
from app.main import app
from app.middleware.rbac import require_approver

_ROLES_DIR = Path(__file__).parent.parent / "roles"


def _cleanup(role_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import PromptVersion

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(PromptVersion).where(PromptVersion.role_name == role_name)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())
    role_file = _ROLES_DIR / f"{role_name}.md"
    if role_file.exists():
        role_file.unlink()


@pytest.fixture
def client():
    app.dependency_overrides[require_approver] = lambda: "test-approver"
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(require_approver, None)


def _deploy(pr: PromptRegistry, role_name: str, content: str, proposed_by: str) -> None:
    v = pr.propose(role_name, content, proposed_by=proposed_by)
    pr.submit_for_review(v.id)
    pr.approve(v.id, "human1")
    pr.deploy(v.id)


def test_history_endpoint_lists_versions_newest_last(client: TestClient) -> None:
    role_name = "td_api_history"
    try:
        pr = PromptRegistry()
        _deploy(pr, role_name, "v1 content", "tester")
        _deploy(pr, role_name, "v2 content", "tester")

        resp = client.get(f"/api/fleet/prompts/{role_name}/history")

        assert resp.status_code == 200
        versions = resp.json()
        assert [v["versionNumber"] for v in versions] == [1, 2]
        assert versions[0]["status"] == "superseded"
        assert versions[1]["status"] == "deployed"
    finally:
        _cleanup(role_name)


def test_rollback_endpoint_restores_prior_version_and_writes_file(
    client: TestClient,
) -> None:
    role_name = "td_api_rollback"
    try:
        pr = PromptRegistry()
        _deploy(pr, role_name, "v1 content", "tester")
        _deploy(pr, role_name, "v2 content (bad)", "tester")

        resp = client.post(f"/api/fleet/prompts/{role_name}/rollback")

        assert resp.status_code == 200
        body = resp.json()
        assert body["versionNumber"] == 1
        assert body["status"] == "deployed"
        assert body["rolledBackBy"] == "test-approver"

        # The real file on disk reflects the rollback — load_role() reads
        # this file fresh on every agent call, no restart required.
        assert _role_file_path(role_name).read_text(encoding="utf-8") == "v1 content"

        # And the registry's own history agrees: v1 deployed, v2 superseded.
        history = pr.get_history(role_name)
        by_version = {v.version_number: v.status for v in history}
        assert by_version[1] == "deployed"
        assert by_version[2] == "superseded"
    finally:
        _cleanup(role_name)


def test_rollback_endpoint_404_when_nothing_superseded(client: TestClient) -> None:
    role_name = "td_api_rollback_404"
    try:
        pr = PromptRegistry()
        _deploy(pr, role_name, "only version", "tester")

        resp = client.post(f"/api/fleet/prompts/{role_name}/rollback")

        assert resp.status_code == 404
    finally:
        _cleanup(role_name)


def test_rollback_endpoint_requires_approver_role() -> None:
    # No require_approver override here — the real RBAC dependency must
    # reject an anonymous caller (matches app.config.get_settings()'s
    # rbac_enabled default in this dev environment).
    from app.config import get_settings

    if not get_settings().rbac_enabled:
        pytest.skip("RBAC disabled in this environment (local dev default)")

    with TestClient(app) as c:
        resp = c.post("/api/fleet/prompts/td_api_no_auth/rollback")
    assert resp.status_code in (401, 403)
