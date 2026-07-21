"""Day 2 agents — structural and handler tests (no real LLM calls)."""
from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tool list imports
# ---------------------------------------------------------------------------
from app.agents.tools import (
    BUG_FIX_TOOLS,
    SECURITY_REVIEWER_TOOLS,
    ARCH_REVIEWER_TOOLS,
    REFACTOR_AGENT_TOOLS,
    MONITORING_AGENT_TOOLS,
    READ_ONLY_TOOLS,
    make_bug_fix_handlers,
    make_security_reviewer_handlers,
    make_arch_reviewer_handlers,
    make_sql_agent_handlers,
    make_docker_agent_handlers,
    make_cicd_agent_handlers,
    make_refactor_agent_handlers,
    make_readme_agent_handlers,
    make_api_docs_agent_handlers,
    make_dependency_agent_handlers,
    make_monitoring_agent_handlers,
)

# ---------------------------------------------------------------------------
# Agent module imports (confirms no syntax/import errors)
# ---------------------------------------------------------------------------
from app.agents.agent_result import AgentResult
from app.agents.bug_fix import run_bug_fix  # noqa: F401
from app.agents.security_reviewer import run_security_review  # noqa: F401
from app.agents.architecture_reviewer import run_arch_review  # noqa: F401
from app.agents.sql_agent import run_sql_agent  # noqa: F401
from app.agents.docker_agent import run_docker_agent  # noqa: F401
from app.agents.cicd_agent import run_cicd_agent  # noqa: F401
from app.agents.refactor_agent import run_refactor_agent  # noqa: F401
from app.agents.readme_agent import run_readme_agent  # noqa: F401
from app.agents.api_docs_agent import run_api_docs_agent  # noqa: F401
from app.agents.dependency_agent import run_dependency_agent  # noqa: F401
from app.agents.monitoring_agent import run_monitoring_agent  # noqa: F401


def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {t["name"] for t in tool_list}


READ_ONLY_NAMES = _tool_names(READ_ONLY_TOOLS)


# ===========================================================================
# Tool list structure tests
# ===========================================================================

class TestBugFixTools:
    def test_includes_read_only_tools(self) -> None:
        names = _tool_names(BUG_FIX_TOOLS)
        assert READ_ONLY_NAMES.issubset(names)

    def test_includes_analysis_tools(self) -> None:
        names = _tool_names(BUG_FIX_TOOLS)
        for expected in ("parse_ast", "call_graph", "find_function_body", "analyze_error", "read_logs"):
            assert expected in names, f"BUG_FIX_TOOLS missing {expected}"

    def test_includes_write_tools(self) -> None:
        names = _tool_names(BUG_FIX_TOOLS)
        assert "edit_file" in names
        assert "write_file" in names

    def test_includes_submit_tool(self) -> None:
        assert "submit_bug_fix" in _tool_names(BUG_FIX_TOOLS)

    def test_no_bash(self) -> None:
        assert "bash" not in _tool_names(BUG_FIX_TOOLS)


class TestSecurityReviewerTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(SECURITY_REVIEWER_TOOLS))

    def test_includes_security_tools(self) -> None:
        names = _tool_names(SECURITY_REVIEWER_TOOLS)
        for expected in ("secrets_scan", "find_sql", "find_config", "find_api", "find_route"):
            assert expected in names, f"SECURITY_REVIEWER_TOOLS missing {expected}"

    def test_no_write_tools(self) -> None:
        names = _tool_names(SECURITY_REVIEWER_TOOLS)
        assert "write_file" not in names
        assert "edit_file" not in names
        assert "bash" not in names

    def test_includes_submit_tool(self) -> None:
        assert "submit_security_report" in _tool_names(SECURITY_REVIEWER_TOOLS)


class TestArchReviewerTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(ARCH_REVIEWER_TOOLS))

    def test_includes_ast_tools(self) -> None:
        names = _tool_names(ARCH_REVIEWER_TOOLS)
        for expected in ("import_graph", "circular_dep_detect", "dead_code_detect", "parse_ast"):
            assert expected in names, f"ARCH_REVIEWER_TOOLS missing {expected}"

    def test_no_write_tools(self) -> None:
        names = _tool_names(ARCH_REVIEWER_TOOLS)
        assert "write_file" not in names
        assert "bash" not in names

    def test_includes_submit_tool(self) -> None:
        assert "submit_arch_review" in _tool_names(ARCH_REVIEWER_TOOLS)


class TestMonitoringAgentTools:
    def test_includes_monitoring_tools(self) -> None:
        names = _tool_names(MONITORING_AGENT_TOOLS)
        for expected in ("cpu_usage", "memory_usage", "disk_usage", "health_check", "task_progress", "read_logs"):
            assert expected in names, f"MONITORING_AGENT_TOOLS missing {expected}"

    def test_no_write_tools(self) -> None:
        names = _tool_names(MONITORING_AGENT_TOOLS)
        assert "write_file" not in names
        assert "bash" not in names

    def test_includes_submit_tool(self) -> None:
        assert "submit_monitoring_report" in _tool_names(MONITORING_AGENT_TOOLS)


class TestRefactorAgentTools:
    def test_includes_ast_tools(self) -> None:
        names = _tool_names(REFACTOR_AGENT_TOOLS)
        for expected in ("list_functions", "list_classes", "parse_ast", "call_graph", "import_graph"):
            assert expected in names

    def test_includes_write_and_rename(self) -> None:
        names = _tool_names(REFACTOR_AGENT_TOOLS)
        assert "edit_file" in names
        assert "rename_symbol" in names
        assert "replace_function" in names

    def test_includes_bash_for_linting(self) -> None:
        assert "bash" in _tool_names(REFACTOR_AGENT_TOOLS)

    def test_includes_submit_tool(self) -> None:
        assert "submit_refactor_report" in _tool_names(REFACTOR_AGENT_TOOLS)


# ===========================================================================
# Handler factory tests
# ===========================================================================

@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sample.py").write_text(
        "def hello():\n    return 'hi'\n\ndef goodbye():\n    return 'bye'\n"
    )
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n")
    return tmp_path


class TestBugFixHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        for key in ("parse_ast", "call_graph", "find_function_body", "analyze_error",
                    "read_logs", "edit_file", "write_file", "git_diff", "submit_bug_fix"):
            assert key in h, f"make_bug_fix_handlers missing {key}"

    def test_parse_ast_returns_json(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        result = h["parse_ast"]({"path": "src/sample.py"})
        assert "hello" in result
        assert "goodbye" in result

    def test_call_graph_returns_text(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        result = h["call_graph"]({"path": "src/sample.py"})
        assert "sample.py" in result or "hello" in result or "no calls" in result

    def test_analyze_error_extracts_markers(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        tb = "Traceback (most recent call last):\n  File 'app.py', line 10, in run\nValueError: bad input"
        result = h["analyze_error"]({"traceback": tb})
        assert "ValueError" in result or "File" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        h["submit_bug_fix"]({"root_cause": "rc", "fix_summary": "fs", "files_changed": ["a.py"]})
        assert h["_bug_fix_result"]["root_cause"] == "rc"

    def test_write_file_blocked_on_protected(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        result = h["write_file"]({"path": ".env", "content": "SECRET=bad"})
        assert "POLICY DENIED" in result

    def test_edit_file_missing_file(self, tmp_repo: Path) -> None:
        h = make_bug_fix_handlers(str(tmp_repo))
        result = h["edit_file"]({"path": "nonexistent.py", "old_string": "x", "new_string": "y"})
        assert "ERROR" in result


class TestSecurityReviewerHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_security_reviewer_handlers(str(tmp_repo))
        for key in ("secrets_scan", "find_sql", "find_config", "find_api", "find_route",
                    "submit_security_report"):
            assert key in h

    def test_secrets_scan_clean_repo(self, tmp_repo: Path) -> None:
        h = make_security_reviewer_handlers(str(tmp_repo))
        result = h["secrets_scan"]({})
        assert "✅" in result or "No obvious" in result

    def test_secrets_scan_detects_hardcoded(self, tmp_repo: Path) -> None:
        (tmp_repo / "src" / "bad.py").write_text("api_key = 'sk-abc123longerthan8chars'\n")
        h = make_security_reviewer_handlers(str(tmp_repo))
        result = h["secrets_scan"]({})
        assert "⚠️" in result or "potential" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_security_reviewer_handlers(str(tmp_repo))
        h["submit_security_report"]({"severity": "low", "findings": ["x"], "recommendations": ["y"]})
        assert h["_security_result"]["severity"] == "low"

    def test_no_write_handler(self, tmp_repo: Path) -> None:
        h = make_security_reviewer_handlers(str(tmp_repo))
        assert "write_file" not in h
        assert "edit_file" not in h


class TestArchReviewerHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_arch_reviewer_handlers(str(tmp_repo))
        for key in ("import_graph", "circular_dep_detect", "dead_code_detect", "parse_ast",
                    "list_functions", "list_classes", "call_graph", "submit_arch_review"):
            assert key in h

    def test_import_graph_on_python_file(self, tmp_repo: Path) -> None:
        (tmp_repo / "src" / "mod.py").write_text("from pathlib import Path\nimport os\n")
        h = make_arch_reviewer_handlers(str(tmp_repo))
        result = h["import_graph"]({"path": "src/mod.py"})
        assert "pathlib" in result or "os" in result

    def test_circular_dep_detect_clean(self, tmp_repo: Path) -> None:
        h = make_arch_reviewer_handlers(str(tmp_repo))
        result = h["circular_dep_detect"]({"directory": "src"})
        assert "✅" in result or "No circular" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_arch_reviewer_handlers(str(tmp_repo))
        h["submit_arch_review"]({"verdict": "approved", "issues": [], "recommendations": [], "summary": "ok"})
        assert h["_arch_result"]["verdict"] == "approved"


class TestMonitoringHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_monitoring_agent_handlers(str(tmp_repo))
        for key in ("cpu_usage", "memory_usage", "disk_usage", "health_check",
                    "task_progress", "read_logs", "submit_monitoring_report"):
            assert key in h

    def test_memory_usage_returns_string(self, tmp_repo: Path) -> None:
        h = make_monitoring_agent_handlers(str(tmp_repo))
        result = h["memory_usage"]({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_disk_usage_returns_string(self, tmp_repo: Path) -> None:
        h = make_monitoring_agent_handlers(str(tmp_repo))
        result = h["disk_usage"]({"path": "/"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_read_logs_missing_file(self, tmp_repo: Path) -> None:
        h = make_monitoring_agent_handlers(str(tmp_repo))
        result = h["read_logs"]({"path": "nonexistent.log"})
        assert "ERROR" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_monitoring_agent_handlers(str(tmp_repo))
        h["submit_monitoring_report"]({"status": "healthy", "metrics": {"cpu": "5%"}})
        assert h["_monitoring_result"]["status"] == "healthy"

    def test_no_write_handler(self, tmp_repo: Path) -> None:
        h = make_monitoring_agent_handlers(str(tmp_repo))
        assert "write_file" not in h
        assert "edit_file" not in h


class TestRefactorHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_refactor_agent_handlers(str(tmp_repo))
        for key in ("list_functions", "list_classes", "find_function_body", "parse_ast",
                    "call_graph", "import_graph", "rename_symbol", "replace_function",
                    "edit_file", "write_file", "git_diff", "bash", "submit_refactor_report"):
            assert key in h

    def test_bash_policy_denies_arbitrary(self, tmp_repo: Path) -> None:
        h = make_refactor_agent_handlers(str(tmp_repo))
        result = h["bash"]({"command": "rm -rf /tmp/test"})
        assert "POLICY DENIED" in result

    def test_bash_allows_pytest(self, tmp_repo: Path) -> None:
        h = make_refactor_agent_handlers(str(tmp_repo))
        result = h["bash"]({"command": "python -m pytest --version"})
        assert "POLICY DENIED" not in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_refactor_agent_handlers(str(tmp_repo))
        h["submit_refactor_report"]({"summary": "s", "files_changed": ["a.py"]})
        assert h["_refactor_result"]["summary"] == "s"


class TestCicdHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_cicd_agent_handlers(str(tmp_repo))
        for key in ("bash", "edit_file", "write_file", "submit_cicd_report"):
            assert key in h

    def test_bash_allows_git_log(self, tmp_repo: Path) -> None:
        h = make_cicd_agent_handlers(str(tmp_repo))
        result = h["bash"]({"command": "git log --oneline -5"})
        assert "POLICY DENIED" not in result

    def test_bash_denies_npm_install(self, tmp_repo: Path) -> None:
        h = make_cicd_agent_handlers(str(tmp_repo))
        result = h["bash"]({"command": "npm install"})
        assert "POLICY DENIED" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_cicd_agent_handlers(str(tmp_repo))
        h["submit_cicd_report"]({"analysis": "build failed due to missing env var"})
        assert "build failed" in h["_cicd_result"]["analysis"]


class TestDependencyHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_dependency_agent_handlers(str(tmp_repo))
        for key in ("bash", "edit_file", "submit_dependency_report"):
            assert key in h

    def test_bash_allows_pip_list(self, tmp_repo: Path) -> None:
        h = make_dependency_agent_handlers(str(tmp_repo))
        result = h["bash"]({"command": "pip list --format=freeze"})
        assert "POLICY DENIED" not in result

    def test_bash_denies_pip_install(self, tmp_repo: Path) -> None:
        h = make_dependency_agent_handlers(str(tmp_repo))
        result = h["bash"]({"command": "pip install requests"})
        assert "POLICY DENIED" in result

    def test_edit_file_restricted_to_requirements(self, tmp_repo: Path) -> None:
        h = make_dependency_agent_handlers(str(tmp_repo))
        result = h["edit_file"]({"path": "src/sample.py", "old_string": "x", "new_string": "y"})
        assert "POLICY DENIED" in result

    def test_edit_file_allows_requirements(self, tmp_repo: Path) -> None:
        h = make_dependency_agent_handlers(str(tmp_repo))
        result = h["edit_file"]({
            "path": "requirements.txt",
            "old_string": "fastapi==0.111.0",
            "new_string": "fastapi==0.112.0",
        })
        assert "POLICY DENIED" not in result
        assert "Edited" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_dependency_agent_handlers(str(tmp_repo))
        h["submit_dependency_report"]({"outdated": ["fastapi: 0.111 → 0.112"], "upgraded": []})
        assert len(h["_dependency_result"]["outdated"]) == 1


class TestReadmeHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_readme_agent_handlers(str(tmp_repo))
        for key in ("parse_ast", "list_functions", "list_classes", "write_file", "submit_docs"):
            assert key in h

    def test_write_file_allows_md(self, tmp_repo: Path) -> None:
        h = make_readme_agent_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "README.md", "content": "# Test\n"})
        assert "Written" in result
        assert (tmp_repo / "README.md").exists()

    def test_write_file_blocks_py(self, tmp_repo: Path) -> None:
        h = make_readme_agent_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "src/hack.py", "content": "evil()"})
        assert "POLICY DENIED" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_readme_agent_handlers(str(tmp_repo))
        h["submit_docs"]({"files_written": ["README.md"], "summary": "wrote readme"})
        assert h["_docs_result"]["summary"] == "wrote readme"


class TestApiDocsHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_api_docs_agent_handlers(str(tmp_repo))
        for key in ("find_route", "find_api", "parse_ast", "list_functions", "write_file", "submit_docs"):
            assert key in h

    def test_write_file_allows_md(self, tmp_repo: Path) -> None:
        h = make_api_docs_agent_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "docs/API.md", "content": "# API\n"})
        assert "Written" in result

    def test_write_file_blocks_python(self, tmp_repo: Path) -> None:
        h = make_api_docs_agent_handlers(str(tmp_repo))
        result = h["write_file"]({"path": "app/hack.py", "content": ""})
        assert "POLICY DENIED" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_api_docs_agent_handlers(str(tmp_repo))
        h["submit_docs"]({"files_written": ["docs/API.md"], "summary": "api docs"})
        assert h["_docs_result"]["summary"] == "api docs"


class TestSqlAgentHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_sql_agent_handlers(str(tmp_repo))
        for key in ("run_sql", "inspect_schema", "find_sql", "explain_query",
                    "edit_file", "write_file", "submit_sql_report"):
            assert key in h

    def test_run_sql_no_db_url(self, tmp_repo: Path) -> None:
        from unittest.mock import patch, MagicMock
        mock_settings = MagicMock()
        mock_settings.database_url = None
        with patch("app.agents.tools.get_settings", return_value=mock_settings):
            h = make_sql_agent_handlers(str(tmp_repo))
            result = h["run_sql"]({"query": "SELECT 1"})
        assert "ERROR" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_sql_agent_handlers(str(tmp_repo))
        h["submit_sql_report"]({"action": "query", "result": "1 row"})
        assert h["_sql_result"]["action"] == "query"


class TestDockerAgentHandlers:
    def test_handlers_created(self, tmp_repo: Path) -> None:
        h = make_docker_agent_handlers(str(tmp_repo))
        for key in ("docker_ps", "docker_logs", "docker_exec", "docker_compose",
                    "docker_build", "docker_restart", "write_file", "submit_docker_report"):
            assert key in h

    def test_docker_exec_blocks_rm(self, tmp_repo: Path) -> None:
        h = make_docker_agent_handlers(str(tmp_repo))
        result = h["docker_exec"]({"container": "myapp", "command": "rm -rf /data"})
        assert "POLICY DENIED" in result

    def test_docker_compose_blocks_up(self, tmp_repo: Path) -> None:
        h = make_docker_agent_handlers(str(tmp_repo))
        result = h["docker_compose"]({"action": "up"})
        assert "POLICY DENIED" in result

    def test_submit_stores_result(self, tmp_repo: Path) -> None:
        h = make_docker_agent_handlers(str(tmp_repo))
        h["submit_docker_report"]({"action": "inspect", "outcome": "all healthy"})
        assert h["_docker_result"]["outcome"] == "all healthy"


# ===========================================================================
# AgentResult dataclass defaults
# ===========================================================================

class TestAgentResult:
    def test_defaults(self) -> None:
        r = AgentResult(summary="test")
        assert r.summary == "test"
        assert r.findings == []
        assert r.files_touched == []
        assert r.verified is False
        assert r.requires_human_approval is False
        assert r.tokens_in == 0
        assert r.tokens_out == 0
        assert r.status == "completed"
        assert r.raw == {}

    def test_custom_values(self) -> None:
        r = AgentResult(
            summary="done",
            findings=[{"key": "val"}],
            files_touched=["a.py", "b.py"],
            verified=True,
            requires_human_approval=True,
            status="blocked",
        )
        assert r.verified is True
        assert r.requires_human_approval is True
        assert len(r.files_touched) == 2
        assert r.status == "blocked"

    def test_status_values(self) -> None:
        for status in ("completed", "blocked", "needs_approval"):
            r = AgentResult(summary="s", status=status)
            assert r.status == status
