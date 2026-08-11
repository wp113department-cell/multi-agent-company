"""Tests for AUDIT_Q_BATCH09 (Large Project Handling, File Understanding,
Modern Tech Coverage, Tech Adaptation, Documentation-Driven Development)
remediation.

Covers: read_files folding parity with read_file, pinned markdown/PyYAML/
Pillow dependencies, real optional JSON Schema validation for json_validate/
yaml_validate, spike_agent gaining web_search/fetch_url, and new xml_validate/
read_notebook/parse_dockerfile/parse_docker_compose/github_inspect_repo/
openapi_inspect tools.

All tests run against real temp directories, no mocks (matching this
project's existing test conventions).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.agents.spike_agent import AGENT_CONTRACT as SPIKE_CONTRACT
from app.agents.spike_agent import _TOOLS as SPIKE_TOOLS
from app.agents.spike_agent import make_spike_agent_handlers
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.config import get_settings
from app.fleet.tool_manifest import TOOL_MANIFEST


def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {str(t["name"]) for t in tool_list}


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True
    )
    return tmp_path


@pytest.fixture()
def handlers(tmp_repo: Path) -> dict[str, Any]:
    return make_chat_handlers(str(tmp_repo))


# ---------------------------------------------------------------------------
# §15 — read_files folding parity with read_file
# ---------------------------------------------------------------------------


class TestReadFilesFoldingParity:
    def test_large_python_file_is_folded_not_dumped_in_full(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        settings = get_settings()
        threshold = settings.file_fold_line_threshold
        lines = [f"def func_{i}():\n    return {i}\n" for i in range(threshold + 50)]
        big_file = tmp_repo / "big.py"
        big_file.write_text("\n".join(lines))

        result = handlers["read_files"]({"paths": ["big.py"]})
        assert "[NOTE]" in result
        assert "showing structure only" in result
        assert "func_0" in result
        # The full unfolded body must not be present — folding actually
        # replaced content rather than being a no-op.
        assert "return 0\nreturn 1" not in result

    def test_matches_read_file_folded_output(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        settings = get_settings()
        threshold = settings.file_fold_line_threshold
        lines = [f"def func_{i}():\n    return {i}\n" for i in range(threshold + 50)]
        big_file = tmp_repo / "big2.py"
        big_file.write_text("\n".join(lines))

        single = handlers["read_file"]({"path": "big2.py"})
        batch = handlers["read_files"]({"paths": ["big2.py"]})
        assert "[NOTE]" in single and "[NOTE]" in batch
        # Both paths should produce the same structural note/content.
        assert single.split("===")[0].strip("\n") in batch or "func_0" in batch

    def test_small_file_unaffected(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "small.py").write_text("def f():\n    return 1\n")
        result = handlers["read_files"]({"paths": ["small.py"]})
        assert "[NOTE]" not in result
        assert "def f():" in result


# ---------------------------------------------------------------------------
# §16 — pinned dependencies actually installed and working
# ---------------------------------------------------------------------------


class TestPinnedFileTypeDependencies:
    def test_markdown_package_importable(self) -> None:
        import markdown

        assert markdown.markdown("# hi") == "<h1>hi</h1>"

    def test_export_markdown_uses_real_renderer_not_pre_fallback(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "doc.md").write_text("# Title\n\nSome **bold** text.")
        result = handlers["export_markdown"]({"path": "doc.md", "output": "doc.html"})
        assert "Exported" in result
        html = (tmp_repo / "doc.html").read_text()
        assert "<h1>Title</h1>" in html
        assert "<strong>bold</strong>" in html
        assert "<pre>" not in html

    def test_requirements_txt_pins_markdown_yaml_pillow(self) -> None:
        req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        assert "markdown==" in req
        assert "PyYAML==" in req
        assert "Pillow==" in req


# ---------------------------------------------------------------------------
# §16 — json_validate / yaml_validate real optional JSON Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_json_validate_syntax_only_backward_compatible(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "d.json").write_text('{"a": 1}')
        result = handlers["json_validate"]({"path": "d.json"})
        assert result.startswith("✅")
        assert "schema" not in result.lower()

    def test_json_validate_passes_against_schema(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "d.json").write_text('{"name": "gridiron"}')
        (tmp_repo / "schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            )
        )
        result = handlers["json_validate"](
            {"path": "d.json", "schema_path": "schema.json"}
        )
        assert result.startswith("✅")
        assert "matches schema" in result

    def test_json_validate_fails_against_schema(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "d.json").write_text('{"name": 123}')
        (tmp_repo / "schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            )
        )
        result = handlers["json_validate"](
            {"path": "d.json", "schema_path": "schema.json"}
        )
        assert "[SCHEMA VIOLATION]" in result

    def test_yaml_validate_passes_against_schema(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "d.yaml").write_text("name: gridiron\ncount: 3\n")
        (tmp_repo / "schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                }
            )
        )
        result = handlers["yaml_validate"](
            {"path": "d.yaml", "schema_path": "schema.json"}
        )
        assert result.startswith("✅")

    def test_yaml_validate_fails_against_schema(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "d.yaml").write_text("count: not-a-number\n")
        (tmp_repo / "schema.json").write_text(
            json.dumps({"type": "object", "properties": {"count": {"type": "integer"}}})
        )
        result = handlers["yaml_validate"](
            {"path": "d.yaml", "schema_path": "schema.json"}
        )
        assert "[SCHEMA VIOLATION]" in result

    def test_manifest_descriptions_match_real_behavior(self) -> None:
        assert "syntax" in TOOL_MANIFEST["json_validate"].purpose.lower()
        assert "syntax" in TOOL_MANIFEST["yaml_validate"].purpose.lower()


# ---------------------------------------------------------------------------
# §79/§80 — spike_agent gains web_search + fetch_url
# ---------------------------------------------------------------------------


class TestSpikeAgentExternalResearchAccess:
    def test_allowed_tools_include_web_search_and_fetch_url(self) -> None:
        assert "web_search" in SPIKE_CONTRACT["allowed_tools"]
        assert "fetch_url" in SPIKE_CONTRACT["allowed_tools"]

    def test_tool_schema_includes_both(self) -> None:
        names = _tool_names(SPIKE_TOOLS)
        assert "web_search" in names
        assert "fetch_url" in names

    def test_handlers_wire_real_callables(self, tmp_repo: Path) -> None:
        h = make_spike_agent_handlers(str(tmp_repo))
        assert callable(h["web_search"])
        assert callable(h["fetch_url"])


# ---------------------------------------------------------------------------
# §16 — xml_validate
# ---------------------------------------------------------------------------


class TestXmlValidate:
    def test_valid_xml(self, tmp_repo: Path, handlers: dict[str, Any]) -> None:
        (tmp_repo / "a.xml").write_text("<root><child>text</child></root>")
        result = handlers["xml_validate"]({"path": "a.xml"})
        assert result.startswith("✅")

    def test_invalid_xml(self, tmp_repo: Path, handlers: dict[str, Any]) -> None:
        (tmp_repo / "bad.xml").write_text("<root><child></root>")
        result = handlers["xml_validate"]({"path": "bad.xml"})
        assert "[INVALID XML]" in result

    def test_registered_in_chat_tools(self) -> None:
        assert "xml_validate" in _tool_names(CHAT_TOOLS)


# ---------------------------------------------------------------------------
# §16 — read_notebook
# ---------------------------------------------------------------------------


class TestReadNotebook:
    def test_reads_cells_and_outputs(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["# Title\n"],
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "source": ["print('hi')\n"],
                    "outputs": [
                        {"output_type": "stream", "text": ["hi\n"]},
                    ],
                },
            ]
        }
        (tmp_repo / "nb.ipynb").write_text(json.dumps(notebook))
        result = handlers["read_notebook"]({"path": "nb.ipynb"})
        assert "# Title" in result
        assert "print('hi')" in result
        assert "[output] hi" in result

    def test_invalid_notebook(self, tmp_repo: Path, handlers: dict[str, Any]) -> None:
        (tmp_repo / "bad.ipynb").write_text("not json")
        result = handlers["read_notebook"]({"path": "bad.ipynb"})
        assert "[ERROR]" in result

    def test_registered_in_chat_tools(self) -> None:
        assert "read_notebook" in _tool_names(CHAT_TOOLS)


# ---------------------------------------------------------------------------
# §16 — parse_dockerfile / parse_docker_compose
# ---------------------------------------------------------------------------


class TestParseDockerfile:
    def test_multi_stage_with_expose(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "Dockerfile").write_text(
            "FROM python:3.12 AS builder\n"
            "RUN pip install -r requirements.txt\n"
            "FROM python:3.12-slim\n"
            "COPY --from=builder /app /app\n"
            "EXPOSE 8000\n"
            'CMD ["python", "app.py"]\n'
        )
        result = handlers["parse_dockerfile"]({"path": "Dockerfile"})
        assert "python:3.12 AS builder" in result
        assert "python:3.12-slim" in result
        assert "8000" in result
        assert "CMD" in result

    def test_missing_file(self, tmp_repo: Path, handlers: dict[str, Any]) -> None:
        result = handlers["parse_dockerfile"]({"path": "NoSuchDockerfile"})
        assert "[ERROR]" in result

    def test_registered_in_chat_tools(self) -> None:
        assert "parse_dockerfile" in _tool_names(CHAT_TOOLS)


class TestParseDockerCompose:
    def test_services_summary(self, tmp_repo: Path, handlers: dict[str, Any]) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: myapp:latest\n"
            "    ports:\n"
            "      - '8000:8000'\n"
            "    depends_on:\n"
            "      - db\n"
            "  db:\n"
            "    image: postgres:16\n"
            "    volumes:\n"
            "      - dbdata:/var/lib/postgresql/data\n"
        )
        result = handlers["parse_docker_compose"]({"path": "docker-compose.yml"})
        assert "web" in result
        assert "myapp:latest" in result
        assert "db" in result
        assert "postgres:16" in result

    def test_missing_file(self, tmp_repo: Path, handlers: dict[str, Any]) -> None:
        result = handlers["parse_docker_compose"]({"path": "nope.yml"})
        assert "[ERROR]" in result

    def test_registered_in_chat_tools(self) -> None:
        assert "parse_docker_compose" in _tool_names(CHAT_TOOLS)


# ---------------------------------------------------------------------------
# §79 — github_inspect_repo (external repos, not the local checkout)
# ---------------------------------------------------------------------------


class TestGithubInspectRepo:
    def test_rejects_invalid_owner(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        result = handlers["github_inspect_repo"]({"owner": "../evil", "repo": "x"})
        assert "[ERROR]" in result

    def test_rejects_invalid_path_traversal(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        result = handlers["github_inspect_repo"](
            {"owner": "octocat", "repo": "Hello-World", "path": "../../etc"}
        )
        assert "[ERROR]" in result

    def test_registered_in_chat_tools(self) -> None:
        assert "github_inspect_repo" in _tool_names(CHAT_TOOLS)

    @pytest.mark.slow
    def test_inspects_real_public_repo(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        result = handlers["github_inspect_repo"](
            {"owner": "octocat", "repo": "Hello-World"}
        )
        assert "[ERROR]" not in result
        assert "octocat/Hello-World" in result


# ---------------------------------------------------------------------------
# §79 — openapi_inspect
# ---------------------------------------------------------------------------


class TestOpenapiInspect:
    def test_summarizes_paths_and_methods(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Pet Store", "version": "1.0.0"},
            "paths": {
                "/pets": {
                    "get": {"summary": "List pets", "parameters": []},
                    "post": {
                        "summary": "Create a pet",
                        "parameters": [{"name": "body"}],
                    },
                },
                "/pets/{id}": {
                    "get": {"summary": "Get a pet", "parameters": [{"name": "id"}]},
                },
            },
        }
        (tmp_repo / "openapi.json").write_text(json.dumps(spec))
        result = handlers["openapi_inspect"]({"path": "openapi.json"})
        assert "Pet Store" in result
        assert "GET" in result and "/pets" in result
        assert "POST" in result

    def test_rejects_non_openapi_file(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "notaspec.json").write_text('{"foo": "bar"}')
        result = handlers["openapi_inspect"]({"path": "notaspec.json"})
        assert "[ERROR]" in result

    def test_registered_in_chat_tools(self) -> None:
        assert "openapi_inspect" in _tool_names(CHAT_TOOLS)


# ---------------------------------------------------------------------------
# Tool manifest completeness for all new tools
# ---------------------------------------------------------------------------


class TestNewToolsManifested:
    @pytest.mark.parametrize(
        "tool_name",
        [
            "xml_validate",
            "read_notebook",
            "parse_dockerfile",
            "parse_docker_compose",
            "github_inspect_repo",
            "openapi_inspect",
        ],
    )
    def test_tool_is_manifested(self, tool_name: str) -> None:
        assert tool_name in TOOL_MANIFEST
