"""AUDIT_Q_BATCH10 — Deployment Intelligence (§19), External Knowledge
(§20), Git Intelligence (§40), Documentation Intelligence (§41) gap-closure
tests.

Real git/filesystem operations throughout (no mocking git or the
filesystem). LLM calls are mocked at the `_llm_<capability>` orchestration
level (never `anthropic.Anthropic` directly) so these tests exercise the
real tool logic — what gets gathered, how the fallback triggers when
generation is unavailable — without a real network call. `subprocess.run`
is mocked only for `docker`/`gh` calls, which need a real daemon/CLI this
sandbox may not have.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.tools import (
    CHAT_TOOLS,
    _llm_generate_text,
    inspect_github_repo,
    inspect_openapi_spec,
    make_chat_handlers,
    make_list_deploy_artifacts_handler,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {str(t["name"]) for t in tool_list}


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True
    )
    return tmp_path


@pytest.fixture()
def handlers(tmp_repo: Path) -> dict[str, Any]:
    return make_chat_handlers(str(tmp_repo))


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_NEW_BATCH10_TOOLS = [
    "review_diff",
    "explain_merge_conflict",
    "inspect_github_repo",
    "inspect_openapi_spec",
    "diagnose_deployment_failure",
]


@pytest.mark.parametrize("tool_name", _NEW_BATCH10_TOOLS)
def test_new_tool_registered_in_chat_tools(tool_name: str) -> None:
    assert tool_name in _tool_names(
        CHAT_TOOLS
    ), f"{tool_name!r} missing from CHAT_TOOLS"


@pytest.mark.parametrize("tool_name", _NEW_BATCH10_TOOLS)
def test_new_tool_has_handler(tool_name: str, handlers: dict[str, Any]) -> None:
    assert tool_name in handlers and callable(handlers[tool_name])


# ---------------------------------------------------------------------------
# Shared LLM-generation helper
# ---------------------------------------------------------------------------


class TestLlmGenerateText:
    def test_returns_text_from_client(self) -> None:
        fake_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hello world")]
        )
        with patch("app.agents.base_graph._make_client"), patch(
            "app.agents.base_graph._call_anthropic", return_value=fake_response
        ):
            assert _llm_generate_text("prompt") == "hello world"

    def test_returns_empty_string_on_failure(self) -> None:
        with patch(
            "app.agents.base_graph._make_client", side_effect=RuntimeError("boom")
        ):
            assert _llm_generate_text("prompt") == ""


# ---------------------------------------------------------------------------
# §40 Git Intelligence — generate_commit_msg real LLM generation
# ---------------------------------------------------------------------------


class TestGenerateCommitMsgLLM:
    def test_uses_generated_message_when_llm_available(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "f.txt").write_text("hello")
        subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_repo), capture_output=True)
        with patch(
            "app.agents.tools._llm_generate_commit_message",
            return_value="feat(core): add f.txt",
        ):
            result = handlers["generate_commit_msg"]({})
        assert "=== Generated commit message ===" in result
        assert "feat(core): add f.txt" in result
        assert "f.txt" in result  # raw stat still included

    def test_falls_back_to_raw_diff_when_llm_unavailable(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "f.txt").write_text("hello")
        subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_repo), capture_output=True)
        with patch("app.agents.tools._llm_generate_commit_message", return_value=""):
            result = handlers["generate_commit_msg"]({})
        assert "=== Generated commit message ===" not in result
        assert "f.txt" in result

    def test_no_staged_changes_still_errors(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        result = handlers["generate_commit_msg"]({})
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# §40 Git Intelligence — create_pr auto-generation
# ---------------------------------------------------------------------------


def _make_diverged_branch(tmp_repo: Path) -> None:
    (tmp_repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=str(tmp_repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(tmp_repo), capture_output=True
    )
    subprocess.run(
        ["git", "branch", "-M", "main"], cwd=str(tmp_repo), capture_output=True
    )
    subprocess.run(
        ["git", "checkout", "-b", "feature"], cwd=str(tmp_repo), capture_output=True
    )
    (tmp_repo / "b.txt").write_text("b")
    subprocess.run(["git", "add", "b.txt"], cwd=str(tmp_repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add b"], cwd=str(tmp_repo), capture_output=True
    )


class TestCreatePrAutoGenerate:
    def test_auto_generates_when_title_and_body_omitted(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        _make_diverged_branch(tmp_repo)
        with patch(
            "app.agents.tools._llm_generate_pr_description",
            return_value=("Add b.txt", "Adds a new file b.txt"),
        ) as mock_gen:
            result = handlers["create_pr"]({})
        mock_gen.assert_called_once()
        assert isinstance(result, str)  # gh likely unauthenticated — must not raise

    def test_explicit_title_and_body_skip_generation(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        with patch("app.agents.tools._llm_generate_pr_description") as mock_gen:
            result = handlers["create_pr"](
                {"title": "Explicit title", "body": "Explicit body"}
            )
        mock_gen.assert_not_called()
        assert isinstance(result, str)

    def test_missing_title_after_failed_generation_errors(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        _make_diverged_branch(tmp_repo)
        with patch(
            "app.agents.tools._llm_generate_pr_description", return_value=("", "")
        ):
            result = handlers["create_pr"]({})
        assert "[ERROR] title is required" in result


# ---------------------------------------------------------------------------
# §40 Git Intelligence — review_diff
# ---------------------------------------------------------------------------


class TestReviewDiff:
    def test_no_changes_errors(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        result = handlers["review_diff"]({})
        assert "[ERROR]" in result

    def test_returns_review_when_llm_available(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "f.txt").write_text("hello")
        subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_repo), capture_output=True)
        with patch(
            "app.agents.tools._llm_review_diff", return_value="Summary: adds f.txt"
        ):
            result = handlers["review_diff"]({})
        assert "=== Review ===" in result
        assert "Summary: adds f.txt" in result

    def test_falls_back_when_llm_unavailable(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "f.txt").write_text("hello")
        subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_repo), capture_output=True)
        with patch("app.agents.tools._llm_review_diff", return_value=""):
            result = handlers["review_diff"]({})
        assert "[ERROR] Review generation unavailable" in result
        assert "f.txt" in result


# ---------------------------------------------------------------------------
# §40 Git Intelligence — explain_merge_conflict
# ---------------------------------------------------------------------------

_SIMPLE_CONFLICT = """context 1
<<<<<<< HEAD
ours
=======
theirs
>>>>>>> other
context 2
"""


class TestExplainMergeConflict:
    def test_no_conflict_markers(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "clean.txt").write_text("no conflicts here")
        result = handlers["explain_merge_conflict"]({"path": "clean.txt"})
        assert "No conflict markers found" in result

    def test_explains_real_conflict_via_llm(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "conflicted.txt").write_text(_SIMPLE_CONFLICT)
        with patch(
            "app.agents.tools._llm_explain_conflict_hunks",
            return_value="Ours kept 'ours', theirs kept 'theirs'.",
        ) as mock_explain:
            result = handlers["explain_merge_conflict"]({"path": "conflicted.txt"})
        mock_explain.assert_called_once()
        assert "Ours kept 'ours', theirs kept 'theirs'." in result

    def test_file_not_found(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        result = handlers["explain_merge_conflict"]({"path": "nope.txt"})
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# §20 External Knowledge — fetch_url summarize
# ---------------------------------------------------------------------------


class TestFetchUrlSummarize:
    def test_summarize_default_false_no_llm_call(
        self, handlers: dict[str, Any]
    ) -> None:
        with patch("app.agents.tools._llm_summarize_url_content") as mock_sum:
            result = handlers["fetch_url"](
                {"url": "http://127.0.0.1:19999/nonexistent", "timeout": 2}
            )
        mock_sum.assert_not_called()
        assert isinstance(result, str)

    def test_ssrf_blocked_even_with_summarize(self, handlers: dict[str, Any]) -> None:
        result = handlers["fetch_url"](
            {"url": "http://169.254.169.254/latest/meta-data/", "summarize": True}
        )
        assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# §20 External Knowledge — inspect_github_repo
# ---------------------------------------------------------------------------


class TestInspectGithubRepo:
    def test_missing_owner_or_repo(self) -> None:
        assert "[ERROR]" in inspect_github_repo({"owner": "", "repo": "x"})
        assert "[ERROR]" in inspect_github_repo({"owner": "x", "repo": ""})

    def test_invalid_identifier_rejected(self) -> None:
        result = inspect_github_repo({"owner": "; rm -rf /", "repo": "x"})
        assert "[ERROR]" in result

    def test_unknown_action(self) -> None:
        result = inspect_github_repo({"owner": "x", "repo": "y", "action": "bogus"})
        assert "[ERROR] Unknown action" in result

    def test_path_traversal_rejected(self) -> None:
        result = inspect_github_repo(
            {
                "owner": "x",
                "repo": "y",
                "action": "read_file",
                "path": "../../etc/passwd",
            }
        )
        assert "[ERROR]" in result

    def test_gh_not_found_graceful(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = inspect_github_repo({"owner": "octo", "repo": "repo"})
        assert "gh CLI not found" in result

    def test_info_action_parses_real_response_shape(self) -> None:
        fake_body = json.dumps(
            {
                "full_name": "octo/repo",
                "description": "desc",
                "default_branch": "main",
                "language": "Python",
                "stargazers_count": 42,
                "open_issues_count": 3,
                "topics": ["a", "b"],
                "license": {"name": "MIT"},
                "homepage": "https://example.com",
                "archived": False,
            }
        )
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=fake_body, stderr=""
        )
        with patch("subprocess.run", return_value=mock_result):
            result = inspect_github_repo(
                {"owner": "octo", "repo": "repo", "action": "info"}
            )
        data = json.loads(result)
        assert data["full_name"] == "octo/repo"
        assert data["stargazers_count"] == 42

    def test_list_files_action(self) -> None:
        fake_body = json.dumps(
            [
                {"name": "README.md", "type": "file", "path": "README.md"},
                {"name": "src", "type": "dir", "path": "src"},
            ]
        )
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=fake_body, stderr=""
        )
        with patch("subprocess.run", return_value=mock_result):
            result = inspect_github_repo(
                {"owner": "octo", "repo": "repo", "action": "list_files"}
            )
        data = json.loads(result)
        assert {"name": "README.md", "type": "file", "path": "README.md"} in data

    def test_read_file_action_decodes_base64(self) -> None:
        import base64

        encoded = base64.b64encode(b"print('hi')").decode()
        fake_body = json.dumps({"encoding": "base64", "content": encoded})
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=fake_body, stderr=""
        )
        with patch("subprocess.run", return_value=mock_result):
            result = inspect_github_repo(
                {
                    "owner": "octo",
                    "repo": "repo",
                    "action": "read_file",
                    "path": "main.py",
                }
            )
        assert result == "print('hi')"

    def test_api_failure_returns_error(self) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="404 Not Found"
        )
        with patch("subprocess.run", return_value=mock_result):
            result = inspect_github_repo({"owner": "octo", "repo": "doesnotexist"})
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# §20 External Knowledge — inspect_openapi_spec
# ---------------------------------------------------------------------------

_SAMPLE_OPENAPI_JSON = json.dumps(
    {
        "openapi": "3.0.0",
        "info": {"title": "Sample API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "summary": "List users",
                    "operationId": "listUsers",
                    "parameters": [{"name": "limit"}],
                },
                "post": {"summary": "Create user", "operationId": "createUser"},
            },
            "/users/{id}": {
                "get": {
                    "summary": "Get user",
                    "operationId": "getUser",
                    "parameters": [{"name": "id"}],
                },
            },
        },
        "components": {"schemas": {"User": {}, "Error": {}}},
    }
)

_SAMPLE_OPENAPI_YAML = """
openapi: "3.0.0"
info:
  title: Sample API
  version: "1.0.0"
paths:
  /users:
    get:
      summary: List users
      operationId: listUsers
"""


class TestInspectOpenapiSpec:
    def test_missing_input_errors(self) -> None:
        result = inspect_openapi_spec({})
        assert "[ERROR]" in result

    def test_parses_json_spec(self) -> None:
        result = inspect_openapi_spec({"spec_text": _SAMPLE_OPENAPI_JSON})
        data = json.loads(result)
        assert data["openapi_version"] == "3.0.0"
        assert data["title"] == "Sample API"
        assert data["endpoint_count"] == 3
        assert "User" in data["schemas"]
        methods = {e["method"] for e in data["endpoints"]}
        assert methods == {"GET", "POST"}

    def test_parses_yaml_spec(self) -> None:
        result = inspect_openapi_spec({"spec_text": _SAMPLE_OPENAPI_YAML})
        data = json.loads(result)
        assert data["openapi_version"] == "3.0.0"
        assert data["endpoint_count"] == 1

    def test_not_an_openapi_spec_errors(self) -> None:
        result = inspect_openapi_spec({"spec_text": json.dumps({"foo": "bar"})})
        assert "[ERROR]" in result

    def test_unparseable_content_errors(self) -> None:
        result = inspect_openapi_spec({"spec_text": "{not json and: [not valid yaml"})
        assert "[ERROR]" in result

    def test_ssrf_blocked_url(self) -> None:
        result = inspect_openapi_spec({"url": "http://169.254.169.254/spec.json"})
        assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# §19 Deployment Intelligence — diagnose_deployment_failure
# ---------------------------------------------------------------------------


class TestDiagnoseDeploymentFailure:
    def test_without_container_gathers_ps_only(self, handlers: dict[str, Any]) -> None:
        ps_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="CONTAINER ID   STATUS\nabc123   Exited (1) 2 min ago",
            stderr="",
        )
        with patch("subprocess.run", return_value=ps_result), patch(
            "app.agents.tools._llm_diagnose_deployment_failure",
            return_value="Container abc123 exited with code 1.",
        ):
            result = handlers["diagnose_deployment_failure"]({})
        assert "docker ps -a" in result
        assert "Container abc123 exited with code 1." in result

    def test_with_container_gathers_logs_and_inspect(
        self, handlers: dict[str, Any]
    ) -> None:
        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            if cmd[:2] == ["docker", "ps"]:
                return subprocess.CompletedProcess(cmd, 0, "CONTAINER...", "")
            if cmd[:2] == ["docker", "logs"]:
                return subprocess.CompletedProcess(cmd, 0, "Error: OOM killed\n", "")
            if cmd[:2] == ["docker", "inspect"]:
                inspect_json = json.dumps(
                    [
                        {
                            "State": {
                                "Status": "exited",
                                "ExitCode": 137,
                                "Error": "",
                                "OOMKilled": True,
                                "StartedAt": "t1",
                                "FinishedAt": "t2",
                            },
                            "RestartCount": 3,
                        }
                    ]
                )
                return subprocess.CompletedProcess(cmd, 0, inspect_json, "")
            raise AssertionError(f"unexpected cmd {cmd}")

        with patch("subprocess.run", side_effect=fake_run), patch(
            "app.agents.tools._llm_diagnose_deployment_failure",
            return_value="OOM diagnosed.",
        ):
            result = handlers["diagnose_deployment_failure"]({"container": "myapp"})
        assert "OOMKilled" in result
        assert "true" in result.lower() or "True" in result
        assert "OOM diagnosed." in result

    def test_diagnosis_unavailable_still_returns_gathered_state(
        self, handlers: dict[str, Any]
    ) -> None:
        ps_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="(none)", stderr=""
        )
        with patch("subprocess.run", return_value=ps_result), patch(
            "app.agents.tools._llm_generate_text", return_value=""
        ):
            result = handlers["diagnose_deployment_failure"]({})
        assert "[ERROR] Diagnosis generation failed" in result


# ---------------------------------------------------------------------------
# §19 Deployment Intelligence — list_deploy_artifacts + deployment_guide_doc_agent
# ---------------------------------------------------------------------------


class TestListDeployArtifacts:
    def test_finds_real_deploy_files_only(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
        (tmp_path / "docker-compose.yml").write_text("services: {}\n")
        (tmp_path / "Procfile").write_text("web: gunicorn app:app\n")
        (tmp_path / "README.md").write_text("# Not a deploy artifact\n")
        gh = tmp_path / ".github" / "workflows"
        gh.mkdir(parents=True)
        (gh / "ci.yml").write_text("name: CI\n")

        handler = make_list_deploy_artifacts_handler(str(tmp_path))
        data = json.loads(handler({}))
        found = set(data["deploy_artifacts"])
        assert "Dockerfile" in found
        assert "docker-compose.yml" in found
        assert "Procfile" in found
        assert ".github/workflows/ci.yml" in found
        assert "README.md" not in found

    def test_empty_repo_returns_empty_list(self, tmp_path: Path) -> None:
        handler = make_list_deploy_artifacts_handler(str(tmp_path))
        data = json.loads(handler({}))
        assert data["deploy_artifacts"] == []

    def test_no_duplicate_entries_across_overlapping_globs(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
        handler = make_list_deploy_artifacts_handler(str(tmp_path))
        data = json.loads(handler({}))
        assert data["deploy_artifacts"].count("Dockerfile") == 1


class TestDeploymentGuideDocAgent:
    def test_role_file_loads_without_crashing(self) -> None:
        """Direct regression proof for this batch's flagship finding: the 4
        doc agents cited as crashing on invocation due to missing role
        files were already fixed (verified, not reimplemented) before this
        batch started; this is the newly-added 5th agent's own role file,
        proven the same way."""
        from app.agents.base import load_role

        role_text = load_role("deployment_guide_doc_agent")
        assert len(role_text) > 100

    def test_handlers_created(self, tmp_path: Path) -> None:
        from app.agents.deployment_guide_doc_agent import (
            make_deployment_guide_doc_handlers,
        )

        h = make_deployment_guide_doc_handlers(str(tmp_path))
        for key in ("list_deploy_artifacts", "write_file", "submit_docs"):
            assert key in h

    def test_write_file_allows_md_only(self, tmp_path: Path) -> None:
        from app.agents.deployment_guide_doc_agent import (
            make_deployment_guide_doc_handlers,
        )

        h = make_deployment_guide_doc_handlers(str(tmp_path))
        result = h["write_file"](
            {"path": "docs/DEPLOYMENT.md", "content": "# Deployment\n"}
        )
        assert "Written" in result
        assert (tmp_path / "docs" / "DEPLOYMENT.md").exists()

    def test_write_file_blocks_non_md(self, tmp_path: Path) -> None:
        from app.agents.deployment_guide_doc_agent import (
            make_deployment_guide_doc_handlers,
        )

        h = make_deployment_guide_doc_handlers(str(tmp_path))
        result = h["write_file"]({"path": "deploy.sh", "content": "#!/bin/bash\n"})
        assert "POLICY DENIED" in result

    def test_run_deployment_guide_doc_agent_propagates_real_result(self) -> None:
        final_state = {
            "result": {"files_written": ["docs/DEPLOYMENT.md"], "summary": "done"},
            "verification": {"artifacts_read": True},
            "tokens_in": 10,
            "tokens_out": 5,
            "submitted": True,
        }
        with patch(
            "app.agents.deployment_guide_doc_agent.run_agent_graph",
            return_value=final_state,
        ), patch(
            "app.agents.deployment_guide_doc_agent.make_deployment_guide_doc_handlers",
            return_value={},
        ):
            from app.agents.deployment_guide_doc_agent import (
                run_deployment_guide_doc_agent,
            )

            result = run_deployment_guide_doc_agent(task_id=1, doc_request="doc it")
        assert result.summary == "done"
        assert result.files_touched == ["docs/DEPLOYMENT.md"]
        assert result.verified is True
        assert result.status == "completed"

    def test_registered_in_specialized_agents_dispatch(self) -> None:
        from app.api.specialized_agents import _load_agent_fn, _REGISTRY

        assert "deployment_guide_doc_agent" in _REGISTRY
        fn = _load_agent_fn("deployment_guide_doc_agent")
        assert callable(fn)


@pytest.mark.parametrize(
    "agent_name",
    [
        "architecture_doc_agent",
        "agent_roster_doc_agent",
        "tool_catalog_doc_agent",
        "migration_guide_doc_agent",
        "deployment_guide_doc_agent",
    ],
)
def test_all_doc_agent_role_files_load_without_crashing(agent_name: str) -> None:
    """Cross-validates the audit's flagship finding is closed for every
    real doc agent, not just the newly-added one: load_role() must not
    raise FileNotFoundError for any of them."""
    from app.agents.base import load_role

    role_text = load_role(agent_name)
    assert len(role_text) > 100
