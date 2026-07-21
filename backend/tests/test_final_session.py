"""Tests for the final session — memory category, retention, migration 010, agents × 60, tools × 190."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Resolve paths relative to this file so tests pass regardless of cwd
_BACKEND = Path(__file__).parent.parent  # .../backend/
_ROOT = _BACKEND.parent  # project root (one level above backend/)

import pytest  # noqa: E402

# ---- Tool count ----


def test_total_tools_190() -> None:
    src = (Path(__file__).parent.parent / "app/agents/tools.py").read_text()
    names = set(re.findall(r'"name":\s*"([a-z][a-z0-9_]+)"', src))
    assert len(names) >= 190, f"Expected ≥190 tools, got {len(names)}"


def test_chat_tools_count() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.agents.tools import CHAT_TOOLS

    assert len(CHAT_TOOLS) >= 165


# ---- Agent registry count ----


def test_agent_registry_60() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.api.specialized_agents import _REGISTRY

    assert len(_REGISTRY) >= 60, f"Expected ≥60 agents, got {len(_REGISTRY)}"


def test_all_new_agents_in_registry() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.api.specialized_agents import _REGISTRY

    new_agents = [
        "infra_agent",
        "test_writer_agent",
        "code_explainer_agent",
        "data_pipeline_agent",
        "api_designer_agent",
        "env_checker_agent",
        "cost_estimator_agent",
        "incident_responder_agent",
        "onboarding_agent",
        "localization_agent",
        "accessibility_agent",
        "compliance_agent",
        "load_test_agent",
        "pair_programmer_agent",
        "spike_agent",
        "rollback_agent",
        "runbook_generator_agent",
        "slo_agent",
        "feature_flag_agent",
    ]
    missing = [a for a in new_agents if a not in _REGISTRY]
    assert not missing, f"Missing from registry: {missing}"


def test_all_agent_modules_import() -> None:
    import sys
    import importlib

    sys.path.insert(0, "backend")
    from app.api.specialized_agents import _REGISTRY

    errors = []
    for name, (mod, fn) in _REGISTRY.items():
        try:
            m = importlib.import_module(mod)
            getattr(m, fn)
        except Exception as e:
            errors.append(f"{name}: {e}")
    assert not errors, "Import errors:\n" + "\n".join(errors)


def test_all_new_agent_role_files_exist() -> None:
    new_agents = [
        "infra_agent",
        "test_writer_agent",
        "code_explainer_agent",
        "data_pipeline_agent",
        "api_designer_agent",
        "env_checker_agent",
        "cost_estimator_agent",
        "incident_responder_agent",
        "onboarding_agent",
        "localization_agent",
        "accessibility_agent",
        "compliance_agent",
        "load_test_agent",
        "pair_programmer_agent",
        "spike_agent",
        "rollback_agent",
        "runbook_generator_agent",
        "slo_agent",
        "feature_flag_agent",
        "debugger_agent",
        "test_coverage_agent",
        "code_quality_agent",
        "dependency_security_agent",
        "version_manager_agent",
        "devex_agent",
    ]
    missing = [a for a in new_agents if not (_BACKEND / "roles" / f"{a}.md").exists()]
    assert not missing, f"Missing role files: {missing}"


# ---- Memory category migration ----


def test_migration_010_exists() -> None:
    assert (_BACKEND / "migrations/versions/010_memory_category_retention.py").exists()


def test_migration_010_revision_chain() -> None:
    src = (
        _BACKEND / "migrations/versions/010_memory_category_retention.py"
    ).read_text()
    assert 'revision: str = "010"' in src
    assert "down_revision" in src and '"009"' in src


def test_migration_010_adds_category_column() -> None:
    src = (
        _BACKEND / "migrations/versions/010_memory_category_retention.py"
    ).read_text()
    assert "category" in src
    assert "add_column" in src


# ---- Memory model has category field ----


def test_memory_embedding_model_has_category() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.db.models import MemoryEmbedding

    assert hasattr(
        MemoryEmbedding, "category"
    ), "MemoryEmbedding missing 'category' column"


# ---- Memory API category filter ----


@pytest.mark.asyncio
async def test_memory_patterns_accepts_category_filter() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.api.memory import get_memory_patterns

    mock_db = AsyncMock()

    # dist query
    dist_result = MagicMock()
    dist_result.fetchall.return_value = []

    # count query
    count_result = MagicMock()
    count_result.scalar_one_or_none.return_value = 0

    # recent query
    recent_result = MagicMock()
    recent_result.scalars.return_value.all.return_value = []

    # category dist query
    cat_dist_result = MagicMock()
    cat_dist_result.fetchall.return_value = []

    mock_db.execute = AsyncMock(
        side_effect=[dist_result, count_result, recent_result, cat_dist_result]
    )

    result = await get_memory_patterns(db=mock_db, category="architecture")
    assert result["category"] == "architecture"
    assert "categoryDistribution" in result
    assert "outcomeDistribution" in result


@pytest.mark.asyncio
async def test_memory_patterns_no_filter() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.api.memory import get_memory_patterns

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.scalar_one_or_none.return_value = 5
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_memory_patterns(db=mock_db, category=None)
    assert result["category"] is None
    assert result["total"] == 5


# ---- Retention service ----


def test_retention_service_has_enforce_function() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    from app.services.retention import enforce_retention_policy, start_retention_loop

    assert callable(enforce_retention_policy)
    assert callable(start_retention_loop)


@pytest.mark.asyncio
async def test_enforce_retention_disabled_returns_zero() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    with patch("app.services.retention.get_settings") as mock_settings:
        mock_settings.return_value.log_retention_days = 0
        from app.services.retention import enforce_retention_policy

        count = await enforce_retention_policy()
    assert count == 0


@pytest.mark.asyncio
async def test_enforce_retention_executes_delete() -> None:
    import sys

    sys.path.insert(0, "backend")  # noqa: E702
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 3
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)

    with patch("app.services.retention.get_settings") as mock_s, patch(
        "app.services.retention.get_session_factory", return_value=mock_factory
    ):
        mock_s.return_value.log_retention_days = 90
        from app.services.retention import enforce_retention_policy

        count = await enforce_retention_policy()
    assert count == 3


# ---- Frontend files exist ----


def test_login_page_exists() -> None:
    assert (_ROOT / "apps/web/app/login/page.tsx").exists()


def test_middleware_exists() -> None:
    assert (_ROOT / "apps/web/middleware.ts").exists()


def test_navbar_component_exists() -> None:
    assert (_ROOT / "apps/web/components/NavBar.tsx").exists()


def test_auth_lib_exists() -> None:
    assert (_ROOT / "apps/web/lib/auth.ts").exists()


def test_cost_page_exists() -> None:
    assert (_ROOT / "apps/web/app/cost/page.tsx").exists()


def test_navbar_has_dark_mode_toggle() -> None:
    src = (_ROOT / "apps/web/components/NavBar.tsx").read_text()
    assert "ThemeToggle" in src
    assert "dark" in src.lower()


def test_navbar_has_logout() -> None:
    src = (_ROOT / "apps/web/components/NavBar.tsx").read_text()
    assert "logout" in src.lower() or "Sign out" in src


def test_login_page_calls_auth_login() -> None:
    src = (_ROOT / "apps/web/app/login/page.tsx").read_text()
    assert "login" in src
    assert "/api/auth/login" in src or 'from "../../lib/auth"' in src


def test_cost_page_calls_metrics_api() -> None:
    # 2026-07-20: cost page was consolidated into /metrics (single KPI page) —
    # it now redirects there instead of duplicating the /api/metrics fetch.
    src = (_ROOT / "apps/web/app/cost/page.tsx").read_text()
    assert "redirect" in src
    assert "/metrics" in src
    metrics_src = (_ROOT / "apps/web/app/metrics/page.tsx").read_text()
    assert "metrics" in metrics_src.lower()
    api_src = (_ROOT / "apps/web/lib/api.ts").read_text()
    assert "/api/metrics" in api_src


def test_middleware_protects_routes() -> None:
    src = (_ROOT / "apps/web/middleware.ts").read_text()
    assert "/login" in src
    assert "redirect" in src.lower()
