"""AUDIT_Q_BATCH14 — Extensibility, Enterprise Readiness, Company-Scale/
Multi-Project, Workspace Isolation, Version Awareness, UX Intelligence,
Accessibility (§47, §48, §77, §94, §95, §98, §99, §100) gap-closure tests
(2026-08-12).

Real DB round trips for anything DB-backed (credential vault, repo
persistence) — matches this suite's own established isolated-engine
convention (see test_credential_vault.py / test_repo_persistence.py). LLM
calls are mocked at the `_llm_generate_text` level, never the raw Anthropic
client, matching this codebase's established mocking boundary.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# §47 — dynamic agent discovery / capability-based dispatch
# ---------------------------------------------------------------------------


class TestExtensibilityDynamicRegistry:
    def test_every_static_registry_entry_still_resolves(self) -> None:
        """Backward compatibility: the hardcoded _REGISTRY dict must be
        completely untouched — every existing short-alias name still
        resolves to its real module/function."""
        import importlib

        from app.api import specialized_agents as sa

        for name, (module_path, fn_name) in sa._REGISTRY.items():
            module = importlib.import_module(module_path)
            assert hasattr(module, fn_name), f"{name}: {module_path}.{fn_name} missing"

    def test_new_agent_discoverable_by_module_stem_without_registry_edit(self) -> None:
        """architecture_reviewer.py is registered in _REGISTRY only under
        the alias 'arch_reviewer' — its own module stem must now also
        resolve via the dynamic fallback, with zero _REGISTRY edits,
        proving a brand-new agent (AGENT_CONTRACT + single run_* function)
        would be dispatchable without touching this file."""
        from app.api import specialized_agents as sa

        assert "architecture_reviewer" not in sa._REGISTRY
        fn = sa._discover_agent_fn("architecture_reviewer")
        assert fn is not None
        assert fn.__name__ == "run_arch_review"
        assert sa._agent_is_dispatchable("architecture_reviewer")

    def test_ambiguous_self_improvement_modules_never_guessed(self) -> None:
        """quality_auditor.py declares both run_quality_auditor_scan and
        run_quality_auditor_apply — real ambiguity that must return None
        (never guess) rather than picking one arbitrarily."""
        from app.api import specialized_agents as sa

        assert sa._discover_agent_fn("quality_auditor") is None

    def test_non_agent_module_never_discovered(self) -> None:
        from app.api import specialized_agents as sa

        assert sa._discover_agent_fn("tools") is None
        assert sa._discover_agent_fn("manager") is None

    def test_unknown_name_raises_value_error(self) -> None:
        from app.api import specialized_agents as sa

        with pytest.raises(ValueError):
            sa._load_agent_fn("definitely_not_a_real_agent_xyz")

    def test_discoverable_agent_names_excludes_static_registry_and_non_agents(
        self,
    ) -> None:
        from app.api import specialized_agents as sa

        names = sa._discoverable_agent_names()
        assert "architecture_reviewer" in names
        assert "bug_fix" not in names  # already in _REGISTRY, not "discoverable"
        assert "tools" not in names
        assert "manager" not in names

    def test_runtime_registered_agent_dispatchable_via_fallback(self) -> None:
        """barot_agent gap-closure — a temporary_agent instance is neither
        in the static _REGISTRY nor a real module on disk (it's registered
        at runtime via app.fleet.dynamic_agent_runtime); both
        _agent_is_dispatchable and _load_agent_fn must fall back to it
        rather than 404/ValueError-ing a genuinely resolvable agent."""
        from app.api import specialized_agents as sa
        from app.fleet.dynamic_agent_runtime import (
            register_runtime_agent_fn,
            unregister_runtime_agent_fn,
        )

        def _fake_fn(task_id: int, description: str, repo_path: str) -> str:
            return "ok"

        name = "temporary_agent-runtime-fallback-test"
        assert sa._agent_is_dispatchable(name) is False
        register_runtime_agent_fn(name, _fake_fn)
        try:
            assert sa._agent_is_dispatchable(name) is True
            resolved = sa._load_agent_fn(name)
            assert resolved is _fake_fn
        finally:
            unregister_runtime_agent_fn(name)

        assert sa._agent_is_dispatchable(name) is False
        with pytest.raises(ValueError):
            sa._load_agent_fn(name)


class TestFleetDispatchClosesLifecycleLoop:
    def test_run_specialized_agent_bg_marks_agent_running_then_sleeping(self) -> None:
        """§47's second finding: FleetManager.dispatch() never got a real
        caller that actually invokes the agent and closes out its running
        state. _run_specialized_agent_bg is now that real caller."""
        import asyncio as _asyncio

        from app.agents.agent_result import AgentResult
        from app.api import specialized_agents as sa
        from app.fleet.agent_registry import get_agent_registry

        registry = get_agent_registry()
        agent_name = "test_lifecycle_probe_agent"

        fake_result = AgentResult(
            summary="ok",
            findings=[],
            files_touched=[],
            verified=True,
            requires_human_approval=False,
            tokens_in=1,
            tokens_out=1,
            status="completed",
            raw={},
        )

        async def _run() -> None:
            from contextlib import asynccontextmanager
            from unittest.mock import AsyncMock, MagicMock

            fake_db = MagicMock()

            @asynccontextmanager
            async def _session():
                yield fake_db

            with patch.object(
                sa, "_load_agent_fn", return_value=lambda **kw: fake_result
            ), patch(
                "app.db.session.get_session_factory", return_value=_session
            ), patch.object(
                sa, "append_log", new=AsyncMock()
            ), patch(
                "app.artifacts.store.save_artifact_async", new=AsyncMock()
            ), patch(
                "app.memory.hooks.record_agent_run_outcome", new=AsyncMock()
            ), patch(
                "app.db.repository.get_task_repo_id", new=AsyncMock(return_value=None)
            ), patch(
                "app.api.repo.get_active_repo_path", return_value="."
            ):
                await sa._run_specialized_agent_bg(
                    agent_name=agent_name,
                    task_id=999999,
                    description="probe",
                    repo_path=".",
                )

        _asyncio.run(_run())
        instance = registry.get(agent_name)
        assert instance is not None
        # complete() was called after the (mocked) run finished — agent is
        # back to SLEEP (available), not left RUNNING forever.
        assert instance.is_available


# ---------------------------------------------------------------------------
# §48 — audit log pagination + RBAC route coverage
# ---------------------------------------------------------------------------


class TestAuditLogPagination:
    def test_recent_async_accepts_before_cursor(self) -> None:
        from app.fleet.audit_log import get_audit_log

        async def _run() -> None:
            # No DB required to prove the signature/plumbing accepts the
            # new param and doesn't raise — falls back to the ring buffer
            # gracefully if the DB is unreachable in this test env.
            entries = await get_audit_log().recent_async(5, before=None)
            assert isinstance(entries, list)

        asyncio.run(_run())

    def test_cursor_str_normalizes_datetime_and_string(self) -> None:
        from datetime import datetime, timezone

        from app.api.audit import _cursor_str

        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _cursor_str(dt) == dt.isoformat()
        assert _cursor_str("2026-01-01T00:00:00+00:00") == "2026-01-01T00:00:00+00:00"


_NEWLY_PROTECTED_ROUTES = [
    "/api/tasks",
    "/api/tasks/{task_id}",
    "/api/tasks/{task_id}/logs",
    "/api/tasks/{task_id}/subtasks",
    "/api/tasks/{task_id}/pipeline",
    "/api/tasks/{task_id}/explain",
    "/api/tasks/{task_id}/diff",
    "/api/tasks/{task_id}/pr",
    "/api/tasks/{task_id}/images",
    "/api/tasks/{task_id}/images/{image_id}",
    "/api/fleet/requests",
    "/api/fleet/requests/{request_id}",
    "/api/fleet/reports/cost",
    "/api/fleet/reports/health",
    "/api/fleet/reports/repair-patterns",
    "/api/fleet/requests/stream",
    "/api/memory/patterns",
    "/api/memory/analytics",
    "/api/memory/search",
    "/api/memory/lessons",
    "/api/repo",
    "/api/repo/reindex",
    "/api/repo/context",
    "/api/repo/architecture",
    "/api/repo/class-graph",
    "/api/repo/package-graph",
    "/api/agents",
    "/api/agents/{name}",
    "/api/agents/{name}/metrics",
    "/api/epics",
    "/api/epics/{epic_id}",
    "/api/epics/batch-review",
    "/api/goals",
    "/api/goals/{goal_id}",
]


class TestBatch14RBACRouteCoverage:
    """Names the exact routes this batch tightened, mirroring
    test_batch11_get_route_auth_coverage.py's own precedent so a future
    regression fails with a specific, actionable path."""

    def test_previously_open_routes_now_require_authentication(self) -> None:
        from tests.test_audit05_security_fixes import (
            _collect_dependency_names,
            _iter_leaf_routes,
        )

        from app.main import app

        auth_names = {"require_approver", "require_authenticated", "get_current_user"}
        routes_by_path: dict[str, list] = {}
        for r in _iter_leaf_routes(app):
            path = getattr(r, "path", None)
            if path in _NEWLY_PROTECTED_ROUTES:
                routes_by_path.setdefault(path, []).append(r)

        missing = set(_NEWLY_PROTECTED_ROUTES) - routes_by_path.keys()
        assert (
            not missing
        ), f"Expected route(s) not found — path/prefix changed? {missing}"

        still_open: list[str] = []
        for path, routes in routes_by_path.items():
            for route in routes:
                # GET-only check: some paths are shared with an
                # already-protected POST (e.g. /api/tasks); this suite only
                # asserts the GET method this batch actually touched.
                if "GET" not in getattr(route, "methods", {"GET"}):
                    continue
                names = _collect_dependency_names(route.dependant)
                if not (names & auth_names):
                    still_open.append(path)
        assert still_open == [], f"Still unauthenticated: {still_open}"


# ---------------------------------------------------------------------------
# §77/§94 — agent lifecycle states + repo_id FK on indexing tables
# ---------------------------------------------------------------------------


class TestAgentLifecycleStates:
    def test_disable_then_reactivate_round_trip(self) -> None:
        from app.fleet.agent_registry import AgentRegistry, AgentState

        registry = AgentRegistry()
        registry.register("lifecycle_test_agent")

        instance = registry.disable("lifecycle_test_agent", "maintenance")
        assert instance is not None
        assert instance.state == AgentState.DISABLED
        assert instance.is_available is False

        instance = registry.reactivate("lifecycle_test_agent")
        assert instance is not None
        assert instance.state == AgentState.SLEEP
        assert instance.is_available is True

    def test_retire_is_not_undone_by_reactivate(self) -> None:
        from app.fleet.agent_registry import AgentRegistry, AgentState

        registry = AgentRegistry()
        registry.register("retire_test_agent")

        registry.retire("retire_test_agent", "superseded by v2")
        instance = registry.reactivate("retire_test_agent")
        assert instance is not None
        assert instance.state == AgentState.RETIRED
        assert instance.is_available is False

    def test_retired_agent_excluded_from_fleet_manager_selection(self) -> None:
        from app.fleet.agent_registry import AgentRegistry
        from app.fleet.capability_registry import AgentCapability, CapabilityRegistry
        from app.fleet.fleet_manager import FleetManager

        caps = CapabilityRegistry()
        caps.register(
            AgentCapability(
                name="retirable_agent",
                description="test",
                tools=[],
                input_types=[],
                output_types=[],
                capabilities=["probe_capability"],
            )
        )
        agents = AgentRegistry()
        agents.register("retirable_agent")
        agents.retire("retirable_agent", "test retirement")

        fleet = FleetManager(capability_registry=caps, agent_registry=agents)
        assert fleet.select(required_capability="probe_capability") is None

    def test_reseed_restores_retired_state_from_persisted_event(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from app.fleet.agent_registry import (
            AgentRegistry,
            AgentState,
            reseed_health_from_events,
        )
        import app.fleet.agent_registry as ar_module

        fake_row = ("reseed_probe_agent", {"health": "healthy", "state": "retired"})
        mock_result = MagicMock()
        mock_result.all.return_value = [fake_row]
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        fresh_registry = AgentRegistry()
        with patch.object(ar_module, "_agent_registry", fresh_registry):
            seeded = asyncio.run(reseed_health_from_events(mock_db))
        assert seeded == 1
        instance = fresh_registry.get("reseed_probe_agent")
        assert instance is not None
        assert instance.state == AgentState.RETIRED


class TestRepoIdFkThreading:
    def _new_isolated_db_engine(self) -> object:
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.config import get_settings

        return create_async_engine(get_settings().database_url, pool_pre_ping=True)

    def test_persist_repo_index_sets_repo_id_on_all_rows(self, tmp_path: Path) -> None:
        from sqlalchemy import delete, select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import CallEdge, IndexedFile, Repo
        from app.repo_tools.cross_file_graph import build_cross_file_graph
        from app.repo_tools.persistence import persist_repo_index
        from app.repo_tools.scanner import index_repository

        (tmp_path / "math_utils.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n"
        )
        (tmp_path / "calculator.py").write_text(
            "from math_utils import add\n\n"
            "class Calculator:\n"
            "    def sum(self, a: int, b: int) -> int:\n"
            "        return add(a, b)\n"
        )
        repo_path = str(tmp_path)

        async def _run() -> None:
            engine = self._new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    import uuid

                    repo_row = Repo(
                        github_url=f"https://example.test/{uuid.uuid4()}.git",
                        name=tmp_path.name,
                        local_path=repo_path,
                        status="ready",
                    )
                    db.add(repo_row)
                    await db.commit()
                    await db.refresh(repo_row)
                    real_repo_id = repo_row.id

                    try:
                        idx = index_repository(repo_path)
                        graph = build_cross_file_graph(idx)
                        await persist_repo_index(
                            repo_path, idx, graph, db, repo_id=real_repo_id
                        )

                        files = (
                            (
                                await db.execute(
                                    select(IndexedFile).where(
                                        IndexedFile.repo_path == repo_path
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                        assert files, "expected at least one indexed file"
                        assert all(f.repo_id == real_repo_id for f in files)

                        edges = (
                            (
                                await db.execute(
                                    select(CallEdge).where(
                                        CallEdge.repo_path == repo_path
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                        assert edges, "expected at least one call edge"
                        assert all(e.repo_id == real_repo_id for e in edges)
                    finally:
                        await db.execute(
                            delete(IndexedFile).where(
                                IndexedFile.repo_path == repo_path
                            )
                        )
                        await db.execute(
                            delete(CallEdge).where(CallEdge.repo_path == repo_path)
                        )
                        await db.execute(delete(Repo).where(Repo.id == real_repo_id))
                        await db.commit()
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())

    def test_persist_repo_index_repo_id_defaults_to_none(self, tmp_path: Path) -> None:
        """Every pre-existing caller that omits repo_id keeps identical
        (NULL) behavior."""
        from sqlalchemy import delete, select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import IndexedFile
        from app.repo_tools.cross_file_graph import build_cross_file_graph
        from app.repo_tools.persistence import persist_repo_index
        from app.repo_tools.scanner import index_repository

        (tmp_path / "b.py").write_text("def h():\n    pass\n")
        repo_path = str(tmp_path)

        async def _run() -> None:
            engine = self._new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    idx = index_repository(repo_path)
                    graph = build_cross_file_graph(idx)
                    await persist_repo_index(repo_path, idx, graph, db)

                    files = (
                        (
                            await db.execute(
                                select(IndexedFile).where(
                                    IndexedFile.repo_path == repo_path
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert files and all(f.repo_id is None for f in files)

                    await db.execute(
                        delete(IndexedFile).where(IndexedFile.repo_path == repo_path)
                    )
                    await db.commit()
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# §95 — per-repo credential scoping
# ---------------------------------------------------------------------------


class TestCredentialVaultRepoScoping:
    def _new_isolated_db_engine(self) -> object:
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.config import get_settings

        return create_async_engine(get_settings().database_url, pool_pre_ping=True)

    def test_repo_scoped_credential_wins_over_global(self) -> None:
        from app.security.credential_vault import (
            ProjectCredentials,
            get_credential_vault,
        )
        from app.db.repository import delete_setting
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def _run() -> None:
            engine = self._new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    vault = get_credential_vault()
                    await vault.store(
                        db, ProjectCredentials(github_token=SecretStr("global-token"))
                    )
                    await vault.store(
                        db,
                        ProjectCredentials(github_token=SecretStr("repo-7-token")),
                        repo_id=7,
                    )

                    loaded_repo7 = await vault.load(db, repo_id=7)
                    assert (
                        loaded_repo7.github_token.get_secret_value() == "repo-7-token"
                    )

                    # A different repo with no scoped credential falls back
                    # to global, unchanged.
                    loaded_repo8 = await vault.load(db, repo_id=8)
                    assert (
                        loaded_repo8.github_token.get_secret_value() == "global-token"
                    )

                    loaded_global = await vault.load(db)
                    assert (
                        loaded_global.github_token.get_secret_value() == "global-token"
                    )

                    await delete_setting(db, "github_token")
                    await delete_setting(db, "repo:7:github_token")
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())

    def test_repo_scoped_custom_secret_does_not_leak_into_global_listing(self) -> None:
        from app.security.credential_vault import (
            ProjectCredentials,
            get_credential_vault,
        )
        from app.db.repository import delete_setting, list_setting_keys
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def _run() -> None:
            engine = self._new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                    vault = get_credential_vault()
                    await vault.store(
                        db,
                        ProjectCredentials(
                            custom_secrets={"REPO_ONLY_KEY": SecretStr("scoped-val")}
                        ),
                        repo_id=99,
                    )

                    global_keys = await list_setting_keys(db, "custom_secret:")
                    assert "custom_secret:REPO_ONLY_KEY" not in global_keys

                    loaded = await vault.load(db, repo_id=99)
                    assert (
                        loaded.custom_secrets["REPO_ONLY_KEY"].get_secret_value()
                        == "scoped-val"
                    )

                    loaded_unscoped = await vault.load(db)
                    assert "REPO_ONLY_KEY" not in loaded_unscoped.custom_secrets

                    await delete_setting(db, "repo_custom_secret:99:REPO_ONLY_KEY")
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# §98 — semver/git-tag tools wired into a real worker agent
# ---------------------------------------------------------------------------


class TestVersionAwarenessToolWiring:
    def test_version_manager_agent_tools_include_semver_and_git_tag(self) -> None:
        from app.agents.tools import _GIT_TAG_TOOL, _SEMVER_BUMP_TOOL
        from app.agents.version_manager_agent import _TOOLS, AGENT_CONTRACT

        tool_names = {t["name"] for t in _TOOLS}
        assert "git_tag" in tool_names
        assert "semver_bump" in tool_names
        assert _GIT_TAG_TOOL in _TOOLS
        assert _SEMVER_BUMP_TOOL in _TOOLS
        assert "git_tag" in AGENT_CONTRACT["allowed_tools"]
        assert "semver_bump" in AGENT_CONTRACT["allowed_tools"]

    def test_version_manager_handlers_include_real_git_tag_semver_handlers(
        self,
    ) -> None:
        from app.agents.version_manager_agent import make_version_manager_agent_handlers

        handlers = make_version_manager_agent_handlers(".")
        assert callable(handlers.get("git_tag"))
        assert callable(handlers.get("semver_bump"))


# ---------------------------------------------------------------------------
# §99 — real diagram generation + LLM output summarization
# ---------------------------------------------------------------------------


class TestRealDiagramGeneration:
    def test_class_diagram_uses_real_classes_and_bases(self, tmp_path: Path) -> None:
        from app.agents.tools import make_chat_handlers

        (tmp_path / "shapes.py").write_text(
            "class Shape:\n    def area(self):\n        pass\n\n"
            "class Circle(Shape):\n    def area(self):\n        return 1\n"
        )
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["generate_diagram"](
            {
                "description": "shape hierarchy",
                "kind": "classDiagram",
                "path": "shapes.py",
            }
        )
        assert "classDiagram" in out
        assert "Shape <|-- Circle" in out
        assert "MyClass" not in out  # not the old fake placeholder

    def test_flowchart_uses_real_call_edges(self, tmp_path: Path) -> None:
        from app.agents.tools import make_chat_handlers

        (tmp_path / "flow.py").write_text(
            "def outer():\n    return inner()\n\ndef inner():\n    return 1\n"
        )
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["generate_diagram"](
            {"description": "call flow", "kind": "flowchart", "path": "flow.py"}
        )
        assert "outer --> inner" in out
        assert "A[Start]" not in out  # not the old fake placeholder

    def test_falls_back_to_labeled_template_without_path(self, tmp_path: Path) -> None:
        from app.agents.tools import make_chat_handlers

        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["generate_diagram"](
            {"description": "generic", "kind": "flowchart"}
        )
        assert "A[Start]" in out
        assert "derive this from actual code" in out

    def test_class_diagram_falls_back_when_file_has_no_classes(
        self, tmp_path: Path
    ) -> None:
        from app.agents.tools import make_chat_handlers

        (tmp_path / "empty.py").write_text("x = 1\n")
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["generate_diagram"](
            {"description": "nothing here", "kind": "classDiagram", "path": "empty.py"}
        )
        assert "MyClass" in out  # honest fallback, not a fabricated result


class TestSummarizeOutputTool:
    def test_summarize_output_uses_llm_and_respects_focus(self) -> None:
        from app.agents.tools import make_chat_handlers

        handlers = make_chat_handlers(".")
        with patch(
            "app.agents.tools._llm_generate_text", return_value="- key point"
        ) as mock_llm:
            out = handlers["summarize_output"](
                {"text": "a" * 5000, "focus": "errors only"}
            )
        assert out == "- key point"
        prompt = mock_llm.call_args[0][0]
        assert "errors only" in prompt

    def test_summarize_output_falls_back_on_llm_failure(self) -> None:
        from app.agents.tools import make_chat_handlers

        handlers = make_chat_handlers(".")
        with patch("app.agents.tools._llm_generate_text", return_value=""):
            out = handlers["summarize_output"]({"text": "some long text here"})
        assert "summarization unavailable" in out
        assert "some long text here" in out

    def test_summarize_output_rejects_empty_text(self) -> None:
        from app.agents.tools import make_chat_handlers

        handlers = make_chat_handlers(".")
        out = handlers["summarize_output"]({"text": "   "})
        assert "nothing to summarize" in out

    def test_summarize_output_tool_registered_in_chat_tools(self) -> None:
        from app.agents.tools import CHAT_TOOLS

        assert any(t["name"] == "summarize_output" for t in CHAT_TOOLS)


# ---------------------------------------------------------------------------
# ast_engine.get_call_edges — structured extraction reused by generate_diagram
# ---------------------------------------------------------------------------


class TestAstEngineCallEdgesExtraction:
    def test_get_call_edges_matches_build_call_graph_semantics(
        self, tmp_path: Path
    ) -> None:
        from app.repo_tools.ast_engine import build_call_graph, get_call_edges

        f = tmp_path / "sample.py"
        f.write_text("def a():\n    return b()\n\ndef b():\n    return 1\n")

        edges = get_call_edges(str(f))
        assert isinstance(edges, list)
        assert {e["caller"] for e in edges} == {"a", "b"}

        # build_call_graph's formatted text output is unchanged by the
        # extraction (real regression guard on the pre-existing tool).
        text = build_call_graph(str(f))
        assert "a (L1): b" in text
        assert "b (L4): (no calls)" in text

    def test_get_call_edges_missing_function_name_returns_error_string(
        self, tmp_path: Path
    ) -> None:
        from app.repo_tools.ast_engine import get_call_edges

        f = tmp_path / "sample2.py"
        f.write_text("def a():\n    pass\n")
        result = get_call_edges(str(f), function_name="does_not_exist")
        assert isinstance(result, str)
        assert result.startswith("[ERROR]")
