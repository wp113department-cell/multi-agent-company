"""Production audit 02 (2026-09-29) — write scope of three "write_docs" agents.

api_designer_agent, data_pipeline_agent and load_test_agent declare
permissions=["read_repo", "write_docs", ...] but inherited make_chat_handlers()'s
unscoped write_file; the audit's docs_agent_write_probe.py created evil.py and
could overwrite main.py through them. Real handlers, real files — no mocks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.api_designer_agent import make_api_designer_agent_handlers
from app.agents.data_pipeline_agent import make_data_pipeline_agent_handlers
from app.agents.load_test_agent import make_load_test_agent_handlers

FACTORIES = {
    "api_designer_agent": (make_api_designer_agent_handlers, "api/openapi.yaml"),
    "data_pipeline_agent": (make_data_pipeline_agent_handlers, "pipelines/etl.yaml"),
    "load_test_agent": (make_load_test_agent_handlers, "loadtests/locustfile.py"),
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "main.py").write_text("print('original')\n")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize("agent", sorted(FACTORIES))
def test_cannot_overwrite_existing_code_or_config(repo: Path, agent: str) -> None:
    factory, _ = FACTORIES[agent]
    write = factory(str(repo))["write_file"]
    for target in ("main.py", "docker-compose.yml"):
        before = (repo / target).read_text()
        result = write({"path": target, "content": "OVERWRITTEN\n"})
        assert result.startswith("[POLICY DENIED]"), (agent, target, result)
        assert (repo / target).read_text() == before


@pytest.mark.parametrize("agent", sorted(FACTORIES))
def test_markdown_and_docs_writes_still_work(repo: Path, agent: str) -> None:
    factory, _ = FACTORIES[agent]
    write = factory(str(repo))["write_file"]
    assert not write({"path": "docs/design.md", "content": "# d\n"}).startswith(
        "[POLICY"
    )
    assert (repo / "docs" / "design.md").exists()


@pytest.mark.parametrize("agent", sorted(FACTORIES))
def test_own_new_deliverable_file_type_still_allowed(repo: Path, agent: str) -> None:
    factory, new_path = FACTORIES[agent]
    write = factory(str(repo))["write_file"]
    result = write({"path": new_path, "content": "x: 1\n"})
    assert not result.startswith("[POLICY"), result
    assert (repo / new_path).exists()


def test_api_designer_cannot_create_new_python_code(repo: Path) -> None:
    # (data_pipeline_agent may: its role file's output contract includes
    # .py implementation stubs — test_submit_data_pipeline_agent_hardening.py)
    for agent in ("api_designer_agent",):
        factory, _ = FACTORIES[agent]
        result = factory(str(repo))["write_file"]({"path": "evil.py", "content": "x"})
        assert result.startswith("[POLICY DENIED]"), (agent, result)
        assert not (repo / "evil.py").exists()
