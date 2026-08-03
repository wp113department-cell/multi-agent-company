"""Stage 2 Day 53 — 4 new doc generators (answers.md Q41: "Architecture
docs"/"Agent docs"/"Tool docs"/"Migration guides" all NOT FOUND — no
generator at all), reusing readme_agent.py/api_docs_agent.py's own
established pattern (real repo-grounded read-only + write_file(*.md-scoped)
+ submit_docs), per PLAN.md's own Days 51-53 "Reuse" column.

Also covers a real, pre-existing bug found while wiring these 4 into
app/api/specialized_agents.py's dispatch registry: readme_agent/
api_docs_agent's real second parameter is named `doc_request`, not
`description` — _run_specialized_agent_bg always called them with
description=description, raising TypeError (silently caught and logged),
so dispatching either agent via POST /api/specialized-agents/{name}/run has
always failed. Fixed generally in _agent_call_kwargs().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.agent_roster_doc_agent import (
    make_agent_roster_doc_handlers,
    run_agent_roster_doc_agent,
)
from app.agents.architecture_doc_agent import (
    make_architecture_doc_handlers,
    run_architecture_doc_agent,
)
from app.agents.migration_guide_doc_agent import (
    make_migration_guide_doc_handlers,
    run_migration_guide_doc_agent,
)
from app.agents.tool_catalog_doc_agent import (
    make_tool_catalog_doc_handlers,
    run_tool_catalog_doc_agent,
)
from app.agents.tools import (
    list_all_tool_specs,
    list_migrations,
    list_registered_agents,
)
from app.api.specialized_agents import _agent_call_kwargs, _REGISTRY, _load_agent_fn

# ---------------------------------------------------------------------------
# Real introspection tools — pure-function coverage
# ---------------------------------------------------------------------------


class TestListRegisteredAgents:
    def test_returns_real_agents_including_new_ones(self) -> None:
        data = json.loads(list_registered_agents({}))
        names = {a["name"] for a in data}
        assert "readme_agent" in names  # a real, long-existing agent
        assert "architecture_doc_agent" in names  # this day's own new agent
        assert "agent_roster_doc_agent" in names

    def test_every_entry_has_real_contract_fields(self) -> None:
        data = json.loads(list_registered_agents({}))
        assert len(data) > 0
        for entry in data:
            assert entry["name"]
            assert isinstance(entry["tools"], list)
            assert entry["risk_level"] in ("low", "medium", "high")

    def test_no_duplicate_capability_tags_across_fleet(self) -> None:
        """Regression guard for CLAUDE.md's own rule: capability tags must be
        unique across every registered agent — no two agents claim the same
        tag. Real fleet-wide check, not per-agent."""
        from app.fleet.capability_registry import get_capability_registry

        seen: dict[str, str] = {}
        dupes = []
        for cap in get_capability_registry().all():
            for tag in cap.capabilities:
                if tag in seen and seen[tag] != cap.name:
                    dupes.append((tag, seen[tag], cap.name))
                else:
                    seen[tag] = cap.name
        assert dupes == []


class TestListAllToolSpecs:
    def test_returns_real_deduplicated_tool_specs(self) -> None:
        data = json.loads(list_all_tool_specs({}))
        names = [t["name"] for t in data]
        assert len(names) == len(set(names))  # deduplicated
        assert "write_file" in names
        assert "list_registered_agents" in names  # this day's own new tool


class TestListMigrations:
    def test_returns_real_migration_files_with_parsed_revision(self) -> None:
        data = json.loads(list_migrations({}))
        assert len(data) > 0
        first = next(m for m in data if m["file"] == "001_initial_schema.py")
        assert first["revision"] == "001"
        assert first["down_revision"] is None

    def test_annotated_assignment_revision_is_parsed(self) -> None:
        """Regression guard for the real bug found and fixed while building
        this tool: Alembic's real generated files use annotated assignments
        (`revision: str = "001"`, an ast.AnnAssign), not plain ast.Assign —
        an earlier draft of this parser silently returned revision=None for
        every single real migration file until this was caught."""
        data = json.loads(list_migrations({}))
        with_revision = [m for m in data if m["revision"] is not None]
        assert len(with_revision) == len(data)  # every real file parsed correctly

    def test_chain_links_via_down_revision(self) -> None:
        data = json.loads(list_migrations({}))
        by_revision = {m["revision"]: m for m in data}
        m26 = by_revision.get("026")
        assert m26 is not None
        assert m26["down_revision"] == "025"


# ---------------------------------------------------------------------------
# Per-agent handler + write-scoping coverage (mirrors
# test_day2_agents.py::TestReadmeHandlers exactly)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestArchitectureDocHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_architecture_doc_handlers(str(tmp_repo))
        for key in ("import_graph", "circular_dep_detect", "write_file", "submit_docs"):
            assert key in h

    def test_write_file_allows_md(self, tmp_repo: Path) -> None:
        h = make_architecture_doc_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "ARCHITECTURE.md", "content": "# Arch\n"})
        assert "Written" in result
        assert (tmp_repo / "ARCHITECTURE.md").exists()

    def test_write_file_blocks_py(self, tmp_repo: Path) -> None:
        h = make_architecture_doc_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "src/hack.py", "content": "evil()"})
        assert "POLICY DENIED" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_architecture_doc_handlers(str(tmp_repo))
        h["submit_docs"](
            {"files_written": ["ARCHITECTURE.md"], "summary": "wrote arch"}
        )
        assert h["_docs_result"]["summary"] == "wrote arch"


class TestAgentRosterDocHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_agent_roster_doc_handlers(str(tmp_repo))
        for key in ("list_registered_agents", "write_file", "submit_docs"):
            assert key in h

    def test_list_registered_agents_handler_returns_real_data(
        self, tmp_repo: Path
    ) -> None:
        h = make_agent_roster_doc_handlers(str(tmp_repo))
        data = json.loads(h["list_registered_agents"]({}))
        assert any(a["name"] == "agent_roster_doc_agent" for a in data)

    def test_write_file_allows_docs_path(self, tmp_repo: Path) -> None:
        h = make_agent_roster_doc_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "docs/AGENTS.md", "content": "# Agents\n"})
        assert "Written" in result
        assert (tmp_repo / "docs" / "AGENTS.md").exists()

    def test_write_file_blocks_non_md(self, tmp_repo: Path) -> None:
        h = make_agent_roster_doc_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "config.yaml", "content": "x: 1"})
        assert "POLICY DENIED" in result


class TestToolCatalogDocHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_tool_catalog_doc_handlers(str(tmp_repo))
        for key in ("list_all_tool_specs", "write_file", "submit_docs"):
            assert key in h

    def test_list_all_tool_specs_handler_returns_real_data(
        self, tmp_repo: Path
    ) -> None:
        h = make_tool_catalog_doc_handlers(str(tmp_repo))
        data = json.loads(h["list_all_tool_specs"]({}))
        assert any(t["name"] == "write_file" for t in data)


class TestMigrationGuideDocHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_migration_guide_doc_handlers(str(tmp_repo))
        for key in ("list_migrations", "write_file", "submit_docs"):
            assert key in h

    def test_list_migrations_handler_returns_real_data(self, tmp_repo: Path) -> None:
        h = make_migration_guide_doc_handlers(str(tmp_repo))
        data = json.loads(h["list_migrations"]({}))
        assert len(data) > 0


# ---------------------------------------------------------------------------
# run_*_doc_agent — mocked run_agent_graph, real AgentResult construction
# (mirrors test_gap49_dependency_scan.py's established mocking pattern)
# ---------------------------------------------------------------------------


def _final_state(verification_key: str, files_written: list[str]) -> dict[str, Any]:
    return {
        "result": {"files_written": files_written, "summary": "done"},
        "verification": {verification_key: True},
        "tokens_in": 10,
        "tokens_out": 5,
        "submitted": True,
    }


def test_run_architecture_doc_agent_propagates_real_result() -> None:
    final_state = _final_state("graph_read", ["ARCHITECTURE.md"])
    with patch(
        "app.agents.architecture_doc_agent.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.architecture_doc_agent.make_architecture_doc_handlers",
        return_value={},
    ):
        result = run_architecture_doc_agent(task_id=1, doc_request="doc it")
    assert result.summary == "done"
    assert result.files_touched == ["ARCHITECTURE.md"]
    assert result.verified is True
    assert result.status == "completed"


def test_run_agent_roster_doc_agent_propagates_real_result() -> None:
    final_state = _final_state("roster_read", ["docs/AGENTS.md"])
    with patch(
        "app.agents.agent_roster_doc_agent.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.agent_roster_doc_agent.make_agent_roster_doc_handlers",
        return_value={},
    ):
        result = run_agent_roster_doc_agent(task_id=1, doc_request="doc it")
    assert result.files_touched == ["docs/AGENTS.md"]
    assert result.verified is True


def test_run_tool_catalog_doc_agent_propagates_real_result() -> None:
    final_state = _final_state("catalog_read", ["docs/TOOLS.md"])
    with patch(
        "app.agents.tool_catalog_doc_agent.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.tool_catalog_doc_agent.make_tool_catalog_doc_handlers",
        return_value={},
    ):
        result = run_tool_catalog_doc_agent(task_id=1, doc_request="doc it")
    assert result.files_touched == ["docs/TOOLS.md"]
    assert result.verified is True


def test_run_migration_guide_doc_agent_propagates_real_result() -> None:
    final_state = _final_state("migrations_read", ["docs/MIGRATIONS.md"])
    with patch(
        "app.agents.migration_guide_doc_agent.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.migration_guide_doc_agent.make_migration_guide_doc_handlers",
        return_value={},
    ):
        result = run_migration_guide_doc_agent(task_id=1, doc_request="doc it")
    assert result.files_touched == ["docs/MIGRATIONS.md"]
    assert result.verified is True


def test_run_agent_reports_blocked_when_not_submitted() -> None:
    final_state = _final_state("graph_read", [])
    final_state["submitted"] = False
    with patch(
        "app.agents.architecture_doc_agent.run_agent_graph", return_value=final_state
    ), patch(
        "app.agents.architecture_doc_agent.make_architecture_doc_handlers",
        return_value={},
    ):
        result = run_architecture_doc_agent(task_id=1, doc_request="doc it")
    assert result.status == "blocked"


# ---------------------------------------------------------------------------
# specialized_agents.py registry + the real _agent_call_kwargs bug fix
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    @pytest.mark.parametrize(
        "agent_name",
        [
            "architecture_doc_agent",
            "agent_roster_doc_agent",
            "tool_catalog_doc_agent",
            "migration_guide_doc_agent",
        ],
    )
    def test_new_agent_registered_and_loadable(self, agent_name: str) -> None:
        assert agent_name in _REGISTRY
        fn = _load_agent_fn(agent_name)
        assert callable(fn)


class TestAgentCallKwargsBugFix:
    """The real, pre-existing bug: readme_agent/api_docs_agent's second
    parameter is `doc_request`, not `description` — _run_specialized_agent_bg
    always called them as description=..., which raises TypeError. Proven
    here both in the abstract (a fake function) and against the real,
    previously-broken production functions."""

    def test_doc_request_named_param_gets_the_description_value(self) -> None:
        def fake_agent(
            task_id: int, doc_request: str, repo_path: str | None = None
        ) -> None:
            pass

        kwargs = _agent_call_kwargs(fake_agent, 1, "the real description text", "/repo")
        assert kwargs == {
            "task_id": 1,
            "doc_request": "the real description text",
            "repo_path": "/repo",
        }
        fake_agent(**kwargs)  # must not raise TypeError

    def test_description_named_param_still_works(self) -> None:
        def fake_agent(
            task_id: int, description: str, repo_path: str | None = None
        ) -> None:
            pass

        kwargs = _agent_call_kwargs(fake_agent, 1, "desc", "/repo")
        assert kwargs == {"task_id": 1, "description": "desc", "repo_path": "/repo"}
        fake_agent(**kwargs)  # must not raise TypeError

    def test_real_readme_agent_no_longer_raises_typeerror(self) -> None:
        """readme_agent.run_readme_agent's real signature uses doc_request —
        this call previously raised TypeError before the fix; the LLM call
        itself is mocked out, but the kwarg-binding must succeed."""
        from app.agents.readme_agent import run_readme_agent

        kwargs = _agent_call_kwargs(run_readme_agent, 1, "write docs", "/repo")
        assert kwargs["doc_request"] == "write docs"
        with patch("app.agents.readme_agent.run_agent_graph") as mock_graph, patch(
            "app.agents.readme_agent.make_readme_agent_handlers", return_value={}
        ):
            mock_graph.return_value = {
                "result": {},
                "verification": {},
                "tokens_in": 0,
                "tokens_out": 0,
                "submitted": False,
            }
            run_readme_agent(**kwargs)  # must not raise TypeError

    def test_real_changelog_agent_description_param_still_works(self) -> None:
        """changelog_agent's real signature already used `description` —
        regression guard that the fix didn't break the agents that were
        already correct."""
        from app.agents.changelog_agent import run_changelog_agent

        kwargs = _agent_call_kwargs(run_changelog_agent, 1, "changelog it", "/repo")
        assert kwargs["description"] == "changelog it"
