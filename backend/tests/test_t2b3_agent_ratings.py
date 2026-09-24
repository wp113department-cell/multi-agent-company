"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #439 "User satisfaction (real, not
proxy)").

A real, explicit thumbs-up/down verdict on a completed agent run, replacing
the audit's own honestly-labeled proxy (app/agents/user_sentiment.py's
regex-based frustration detector — which stays in place for its own
real-time in-conversation purpose, this is a separate signal). Real
Postgres end to end: POST /api/ratings persists a row, GET /api/agents/
{name}/metrics aggregates it into userSatisfactionRate.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.main import app


def _cleanup(agent_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Agent, AgentRating

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(AgentRating).where(AgentRating.agent_name == agent_name)
                )
                await session.execute(delete(Agent).where(Agent.name == agent_name))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_rate_agent_persists_a_real_row() -> None:
    agent_name = "td-t2b3-rating-agent-1"
    with TestClient(app) as client:
        try:
            resp = client.post(
                "/api/ratings",
                json={"agent_name": agent_name, "rating": 1, "task_id": "42"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["ok"] is True
            assert body["rating"] == 1
        finally:
            _cleanup(agent_name)


def test_rejects_an_invalid_rating_value() -> None:
    agent_name = "td-t2b3-rating-agent-invalid"
    with TestClient(app) as client:
        try:
            resp = client.post(
                "/api/ratings", json={"agent_name": agent_name, "rating": 5}
            )
            assert resp.status_code == 422, resp.text
        finally:
            _cleanup(agent_name)


def test_satisfaction_rate_aggregates_real_ratings_and_is_none_with_no_data() -> None:
    agent_name = "td-t2b3-rating-agent-2"
    with TestClient(app) as client:
        reg_resp = client.post(
            "/api/agents",
            json={"name": agent_name, "capability_tags": ["testing"], "tool_list": []},
        )
        assert reg_resp.status_code == 200, reg_resp.text
        try:
            # No ratings yet — "no data" must be None, not a fabricated 0.0.
            resp = client.get(f"/api/agents/{agent_name}/metrics")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["userSatisfactionRate"] is None
            assert body["ratingCount"] == 0

            for rating in (1, 1, 1, -1):
                r = client.post(
                    "/api/ratings", json={"agent_name": agent_name, "rating": rating}
                )
                assert r.status_code == 200, r.text

            resp = client.get(f"/api/agents/{agent_name}/metrics")
            body = resp.json()
            assert body["ratingCount"] == 4
            assert body["userSatisfactionRate"] == 0.75  # 3 up, 1 down
        finally:
            _cleanup(agent_name)


def test_rating_route_is_authenticated_only_not_approver_only() -> None:
    """The deliberate RBAC exception this endpoint carries — feedback is not
    an operation on the platform, so a viewer must be able to rate. Checked
    the same way tests/test_b7_auth_and_agent_authorization.py's own route-
    walking guard does: by dependency name, not a full JWT round trip (that
    guard test is the one that actually proves a viewer JWT gets a 200 here,
    since /api/ratings is in its reviewed allowlist)."""
    from fastapi.routing import APIRoute

    from app.main import app as fastapi_app

    def dependency_names(route: APIRoute, inherited: tuple) -> set[str]:
        names: set[str] = set()

        def walk(d: object) -> None:
            for sub in d.dependencies:  # type: ignore[attr-defined]
                if sub.call is not None:
                    names.add(getattr(sub.call, "__name__", ""))
                walk(sub)

        walk(route.dependant)
        for dep in inherited:
            names.add(getattr(getattr(dep, "dependency", dep), "__name__", ""))
        return names

    found: list[tuple[str, str, set[str]]] = []

    def collect(router: object, prefix: str = "", inherited: tuple = ()) -> None:
        for r in router.routes:  # type: ignore[attr-defined]
            if type(r).__name__ == "_IncludedRouter":
                ctx = r.include_context
                collect(
                    r.original_router,
                    prefix + (getattr(ctx, "prefix", "") or ""),
                    inherited + tuple(getattr(ctx, "dependencies", None) or ()),
                )
            elif isinstance(r, APIRoute):
                for method in r.methods - {"HEAD", "OPTIONS"}:
                    found.append(
                        (method, prefix + r.path, dependency_names(r, inherited))
                    )

    collect(fastapi_app)
    matches = [f for f in found if f[0] == "POST" and f[1] == "/api/ratings"]
    assert len(matches) == 1
    _, _, deps = matches[0]
    assert "require_authenticated" in deps
    assert "require_approver" not in deps
