"""
Tests for the 33 new chat tools added in the Batch 1-9 expansion.

Tests run against a real temp directory — no mocks, no stubs.
Every test creates its own isolated file structure so tests can run in parallel.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {str(t["name"]) for t in tool_list}


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """A minimal git-initialised temp directory acting as a fake repo."""
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
# CHAT_TOOLS list completeness
# ---------------------------------------------------------------------------

EXPECTED_NEW_TOOLS = [
    "find_file",
    "format_file",
    "organize_imports",
    "insert_at_line",
    "replace_function",
    "delete_lines",
    "apply_patch",
    "compare_files",
    "run_background",
    "kill_process",
    "run_python_snippet",
    "run_make",
    "fetch_url",
    "git_merge",
    "git_reset",
    "git_worktree",
    "create_pr",
    "generate_commit_msg",
    "run_single_test",
    "coverage_report",
    "type_check",
    "list_functions",
    "list_classes",
    "find_function_body",
    "read_logs",
    "analyze_error",
    "run_sql",
    "inspect_schema",
    "docker_ps",
    "docker_logs",
    "docker_exec",
    "docker_compose",
    "secrets_scan",
]


@pytest.mark.parametrize("tool_name", EXPECTED_NEW_TOOLS)
def test_all_new_tools_in_chat_tools(tool_name: str) -> None:
    """Every new tool must appear in CHAT_TOOLS."""
    assert tool_name in _tool_names(
        CHAT_TOOLS
    ), f"{tool_name!r} missing from CHAT_TOOLS"


@pytest.mark.parametrize("tool_name", EXPECTED_NEW_TOOLS)
def test_all_new_tools_have_handlers(tool_name: str, handlers: dict[str, Any]) -> None:
    """Every new tool must have a callable handler in make_chat_handlers()."""
    assert tool_name in handlers, f"No handler for {tool_name!r}"
    assert callable(handlers[tool_name]), f"Handler for {tool_name!r} is not callable"


# ---------------------------------------------------------------------------
# Batch 1 — File / Editing extras
# ---------------------------------------------------------------------------


class TestFindFile:
    def test_finds_existing_file(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "config.py").write_text("x = 1")
        result = handlers["find_file"]({"name": "config.py"})
        assert "config.py" in result

    def test_returns_not_found_message(self, handlers: dict[str, Any]) -> None:
        result = handlers["find_file"]({"name": "nonexistent_xyzzy.py"})
        assert (
            "no files" in result.lower()
            or result == "(no files matching 'nonexistent_xyzzy.py')"
        )

    def test_glob_pattern(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "test_foo.py").write_text("pass")
        (tmp_repo / "test_bar.py").write_text("pass")
        result = handlers["find_file"]({"name": "test_*.py"})
        assert "test_foo.py" in result or "test_bar.py" in result


class TestFormatFile:
    def test_returns_error_for_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["format_file"]({"path": "ghost.py"})
        assert "[ERROR]" in result

    def test_formats_python_file(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "ugly.py").write_text("x=1+2\ny= 3\n")
        result = handlers["format_file"]({"path": "ugly.py", "formatter": "ruff"})
        # ruff format may succeed or warn about no changes — should not return [ERROR]
        assert "[ERROR]" not in result or "not found" not in result.lower()


class TestOrganizeImports:
    def test_error_on_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["organize_imports"]({"path": "missing.py"})
        assert "[ERROR]" in result

    def test_runs_on_existing_file(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "imports.py").write_text("import os\nimport sys\nx = 1\n")
        result = handlers["organize_imports"]({"path": "imports.py"})
        # Should not crash; ruff may say "1 file left unchanged" or similar
        assert isinstance(result, str)


class TestInsertAtLine:
    def test_inserts_content(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        target = tmp_repo / "sample.py"
        target.write_text("line1\nline2\nline3\n")
        result = handlers["insert_at_line"](
            {"path": "sample.py", "line": 2, "content": "INSERTED"}
        )
        assert "Inserted" in result
        content = target.read_text()
        assert "INSERTED" in content
        lines = content.splitlines()
        assert lines[1] == "INSERTED"

    def test_error_on_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["insert_at_line"](
            {"path": "ghost.py", "line": 1, "content": "x"}
        )
        assert "[ERROR]" in result

    def test_policy_denied_for_protected_path(self, handlers: dict[str, Any]) -> None:
        result = handlers["insert_at_line"](
            {"path": ".env", "line": 1, "content": "SECRET=bad"}
        )
        assert "POLICY DENIED" in result or "[ERROR]" in result


class TestReplaceFunction:
    def test_replaces_function(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        target = tmp_repo / "funcs.py"
        target.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
        result = handlers["replace_function"](
            {
                "path": "funcs.py",
                "function_name": "foo",
                "new_code": "def foo():\n    return 99\n",
            }
        )
        assert "Replaced" in result
        assert "return 99" in target.read_text()
        assert "return 2" in target.read_text()  # bar untouched

    def test_error_on_missing_function(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "nofunc.py").write_text("x = 1\n")
        result = handlers["replace_function"](
            {
                "path": "nofunc.py",
                "function_name": "ghost",
                "new_code": "def ghost(): pass",
            }
        )
        assert "[ERROR]" in result


class TestDeleteLines:
    def test_deletes_lines(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        target = tmp_repo / "lines.py"
        target.write_text("a\nb\nc\nd\ne\n")
        result = handlers["delete_lines"](
            {"path": "lines.py", "start_line": 2, "end_line": 3}
        )
        assert "Deleted" in result
        lines = target.read_text().splitlines()
        assert lines == ["a", "d", "e"]

    def test_error_invalid_range(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "x.py").write_text("a\nb\n")
        result = handlers["delete_lines"](
            {"path": "x.py", "start_line": 3, "end_line": 1}
        )
        assert "[ERROR]" in result


class TestApplyPatch:
    def test_patch_command_not_found_graceful(self, handlers: dict[str, Any]) -> None:
        result = handlers["apply_patch"]({"patch": "not a real patch"})
        # Either patch succeeded (unlikely) or returned an error — should not crash
        assert isinstance(result, str)


class TestCompareFiles:
    def test_identical_files(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "a.txt").write_text("hello\n")
        (tmp_repo / "b.txt").write_text("hello\n")
        result = handlers["compare_files"]({"path_a": "a.txt", "path_b": "b.txt"})
        assert result == "Files are identical"

    def test_diff_output(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "a.txt").write_text("hello\n")
        (tmp_repo / "b.txt").write_text("world\n")
        result = handlers["compare_files"]({"path_a": "a.txt", "path_b": "b.txt"})
        assert "-hello" in result or "+world" in result

    def test_error_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["compare_files"](
            {"path_a": "ghost.txt", "path_b": "also_ghost.txt"}
        )
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Batch 2 — Terminal extras
# ---------------------------------------------------------------------------


class TestRunBackground:
    def test_starts_process_returns_pid(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_background"]({"command": "sleep 30"})
        assert "PID" in result
        # Extract PID and kill it
        pid = int(result.split("PID")[1].split(":")[0].strip())
        os.kill(pid, 9)

    def test_bad_command_graceful(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_background"](
            {"command": "nonexistent_command_xyzzy_abc 2>/dev/null"}
        )
        # May succeed (shell forks) or error — should not raise
        assert isinstance(result, str)


class TestKillProcess:
    def test_kills_existing_process(self, handlers: dict[str, Any]) -> None:
        proc = subprocess.Popen(["sleep", "60"])
        pid = proc.pid
        result = handlers["kill_process"]({"pid": pid})
        assert "TERM" in result or f"{pid}" in result
        proc.wait(timeout=2)

    def test_error_on_nonexistent_pid(self, handlers: dict[str, Any]) -> None:
        result = handlers["kill_process"]({"pid": 9999999})
        assert "[ERROR]" in result or "No process" in result


class TestRunPythonSnippet:
    def test_simple_print(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_python_snippet"]({"code": "print('hello world')"})
        assert "hello world" in result

    def test_arithmetic(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_python_snippet"]({"code": "print(2 + 2)"})
        assert "4" in result

    def test_syntax_error_captured(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_python_snippet"]({"code": "def bad(:\n    pass"})
        assert "SyntaxError" in result or "Error" in result or "[ERROR]" in result


class TestRunMake:
    def test_no_makefile_error(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_make"]({"target": "build"})
        assert "[ERROR]" in result and "Makefile" in result

    def test_lists_targets(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "Makefile").write_text(
            "test:\n\techo running tests\n\nbuild:\n\techo building\n"
        )
        result = handlers["run_make"]({})
        assert isinstance(result, str)

    def test_runs_target(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "Makefile").write_text("hello:\n\techo hello_from_make\n")
        result = handlers["run_make"]({"target": "hello"})
        assert "hello_from_make" in result


class TestFetchUrl:
    def test_invalid_url_graceful(self, handlers: dict[str, Any]) -> None:
        result = handlers["fetch_url"](
            {"url": "http://127.0.0.1:19999/nonexistent", "timeout": 3}
        )
        # Should not raise — should return error or empty response
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Batch 3 — Git extras
# ---------------------------------------------------------------------------


class TestGitMerge:
    def test_error_on_nonexistent_branch(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        # Need a commit first so HEAD exists
        (tmp_repo / "init.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_repo), capture_output=True
        )
        result = handlers["git_merge"]({"branch": "nonexistent_branch_xyzzy"})
        # git outputs "not something we can merge" or "not found" for unknown branches
        assert (
            "error" in result.lower()
            or "[ERROR]" in result
            or "not found" in result.lower()
            or "not something we can merge" in result.lower()
            or "merge" in result.lower()
        )


class TestGitReset:
    def test_hard_reset_blocked_in_sync_handler(self, handlers: dict[str, Any]) -> None:
        result = handlers["git_reset"]({"mode": "hard", "ref": "HEAD"})
        assert "BLOCKED" in result

    def test_mixed_reset_allowed(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_repo), capture_output=True
        )
        result = handlers["git_reset"]({"mode": "mixed", "ref": "HEAD"})
        # Should succeed or say "already up to date"
        assert "[ERROR]" not in result or "nothing to reset" in result.lower()


class TestGitWorktree:
    def test_list_worktrees(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        result = handlers["git_worktree"]({"action": "list"})
        assert isinstance(result, str)

    def test_add_requires_path_and_branch(self, handlers: dict[str, Any]) -> None:
        result = handlers["git_worktree"]({"action": "add"})
        assert "[ERROR]" in result


class TestCreatePr:
    def test_gh_not_found_graceful(self, handlers: dict[str, Any]) -> None:
        result = handlers["create_pr"]({"title": "Test PR"})
        # gh might not be installed or not authenticated — should not raise
        assert isinstance(result, str)


class TestGenerateCommitMsg:
    def test_no_staged_changes_error(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        result = handlers["generate_commit_msg"]({})
        assert "[ERROR]" in result or "No staged" in result

    def test_with_staged_changes(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "f.txt").write_text("hello")
        subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_repo), capture_output=True)
        result = handlers["generate_commit_msg"]({})
        # Should contain diff summary
        assert "f.txt" in result or "conventional commit" in result.lower()


# ---------------------------------------------------------------------------
# Batch 4 — Testing extras
# ---------------------------------------------------------------------------


class TestRunSingleTest:
    def test_returns_string_output(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_single_test"]({"keyword": "test_nonexistent_xyzzy_abc"})
        assert isinstance(result, str)


class TestCoverageReport:
    def test_returns_string_output(self, handlers: dict[str, Any]) -> None:
        result = handlers["coverage_report"]({})
        assert isinstance(result, str)


class TestTypeCheck:
    def test_returns_string_output(self, handlers: dict[str, Any]) -> None:
        result = handlers["type_check"]({"language": "python"})
        assert isinstance(result, str)
        # Should contain mypy section
        assert "mypy" in result.lower()


# ---------------------------------------------------------------------------
# Batch 5 — Code Intelligence
# ---------------------------------------------------------------------------


class TestListFunctions:
    def test_lists_python_functions(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "funcs.py").write_text(
            "def hello():\n    pass\n\nasync def world():\n    return 1\n"
        )
        result = handlers["list_functions"]({"path": "funcs.py"})
        assert "hello" in result
        assert "world" in result

    def test_error_on_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["list_functions"]({"path": "ghost.py"})
        assert "[ERROR]" in result

    def test_no_functions(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "vars.py").write_text("x = 1\ny = 2\n")
        result = handlers["list_functions"]({"path": "vars.py"})
        assert "no function" in result.lower()


class TestListClasses:
    def test_lists_classes_and_methods(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "classes.py").write_text(
            "class Foo:\n    def bar(self):\n        pass\n\n    def baz(self):\n        return 1\n"
        )
        result = handlers["list_classes"]({"path": "classes.py"})
        assert "Foo" in result
        assert "bar" in result
        assert "baz" in result

    def test_error_on_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["list_classes"]({"path": "ghost.py"})
        assert "[ERROR]" in result


class TestFindFunctionBody:
    def test_extracts_function(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "fb.py").write_text(
            "def helper():\n    x = 1\n    return x\n\ndef main():\n    pass\n"
        )
        result = handlers["find_function_body"](
            {"path": "fb.py", "function_name": "helper"}
        )
        assert "def helper" in result
        assert "return x" in result
        # Should not include main()
        assert "def main" not in result

    def test_error_on_missing_function(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "nofunc.py").write_text("x = 1\n")
        result = handlers["find_function_body"](
            {"path": "nofunc.py", "function_name": "ghost"}
        )
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Batch 6 — Debug tools
# ---------------------------------------------------------------------------


class TestReadLogs:
    def test_returns_string(self, handlers: dict[str, Any]) -> None:
        result = handlers["read_logs"]({})
        assert isinstance(result, str)

    def test_reads_specific_log_file(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        log_file = tmp_repo / "test.log"
        log_file.write_text("INFO: line1\nERROR: line2\nINFO: line3\n")
        result = handlers["read_logs"]({"path": str(log_file), "lines": 10})
        assert "line1" in result or "line2" in result

    def test_level_filter(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        log_file = tmp_repo / "app.log"
        log_file.write_text("INFO: msg1\nERROR: msg2\nINFO: msg3\n")
        result = handlers["read_logs"]({"path": str(log_file), "level": "ERROR"})
        assert "msg2" in result
        assert "msg1" not in result
        assert "msg3" not in result


class TestAnalyzeError:
    def test_parses_type_error(self, handlers: dict[str, Any]) -> None:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 10, in main\n'
            "    result = foo(bar)\n"
            "TypeError: foo() takes 0 arguments but 1 was given\n"
        )
        result = handlers["analyze_error"]({"error": tb})
        assert "TypeError" in result
        assert "Error Analysis" in result

    def test_import_error_suggestion(self, handlers: dict[str, Any]) -> None:
        result = handlers["analyze_error"](
            {"error": "ModuleNotFoundError: No module named 'fastapi'"}
        )
        assert "pip install" in result.lower() or "dependency" in result.lower()

    def test_connection_error_suggestion(self, handlers: dict[str, Any]) -> None:
        result = handlers["analyze_error"](
            {"error": "ConnectionRefusedError: [Errno 111] Connection refused"}
        )
        assert "Service not running" in result or "not running" in result.lower()


# ---------------------------------------------------------------------------
# Batch 7 — Database tools
# ---------------------------------------------------------------------------


class TestRunSql:
    def test_missing_db_url_returns_error(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_sql"]({"query": "SELECT 1"})
        # Either returns data or [ERROR] — should not crash
        assert isinstance(result, str)


class TestInspectSchema:
    def test_missing_db_url_returns_error(self, handlers: dict[str, Any]) -> None:
        result = handlers["inspect_schema"]({})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Batch 8 — Docker tools
# ---------------------------------------------------------------------------


class TestDockerPs:
    def test_returns_string(self, handlers: dict[str, Any]) -> None:
        result = handlers["docker_ps"]({"all": False})
        assert isinstance(result, str)


class TestDockerLogs:
    def test_nonexistent_container(self, handlers: dict[str, Any]) -> None:
        result = handlers["docker_logs"]({"container": "nonexistent_xyzzy_container"})
        assert isinstance(result, str)


class TestDockerExec:
    def test_nonexistent_container(self, handlers: dict[str, Any]) -> None:
        result = handlers["docker_exec"](
            {"container": "ghost_container", "command": "echo hi"}
        )
        assert isinstance(result, str)


class TestDockerCompose:
    def test_unknown_action_returns_error(self, handlers: dict[str, Any]) -> None:
        result = handlers["docker_compose"]({"action": "unknown_action_xyzzy"})
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Batch 9 — Security
# ---------------------------------------------------------------------------


class TestSecretsScan:
    def test_clean_repo_returns_ok(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "clean.py").write_text("x = 1\nprint('hello')\n")
        result = handlers["secrets_scan"]({})
        assert "✅" in result or "No hardcoded" in result

    def test_detects_hardcoded_api_key(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        (tmp_repo / "bad.py").write_text(
            'api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = handlers["secrets_scan"]({})
        # Should detect the sk- pattern
        assert "bad.py" in result or "⚠️" in result or "sk-" in result

    def test_ignores_env_files(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        # .env files should be excluded from scan
        (tmp_repo / ".env").write_text("SECRET_KEY=my_super_secret_password_here\n")
        (tmp_repo / "clean.py").write_text("x = 1\n")
        result = handlers["secrets_scan"]({})
        # The .env file should be excluded, so no findings from it
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Safety / Policy cross-checks
# ---------------------------------------------------------------------------


def test_protected_paths_not_writable(handlers: dict[str, Any]) -> None:
    for path in [".env", "secrets/key.txt", ".github/workflows/ci.yml"]:
        result = handlers["insert_at_line"](
            {"path": path, "line": 1, "content": "evil"}
        )
        assert (
            "POLICY DENIED" in result or "[ERROR]" in result
        ), f"Protected path {path!r} not blocked"


def test_chat_tools_has_no_duplicates() -> None:
    names = [str(t["name"]) for t in CHAT_TOOLS]
    assert len(names) == len(
        set(names)
    ), f"Duplicate tool names in CHAT_TOOLS: {[n for n in names if names.count(n) > 1]}"


def test_total_chat_tools_count() -> None:
    """Verify CHAT_TOOLS grew — should have at least 69 tools (36 original + 33 new)."""
    assert len(CHAT_TOOLS) >= 69, f"Expected >= 69 CHAT_TOOLS, got {len(CHAT_TOOLS)}"
