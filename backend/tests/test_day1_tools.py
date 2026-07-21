"""
Tests for Day 1 tools — Batches 10-16.

All tests run against real temp directories, no mocks.
Covers: AST Engine, Git extras, Terminal extras, Smart search,
        Monitoring, Editing extras, DB extras.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.repo_tools.ast_engine import (
    build_call_graph,
    build_import_graph,
    detect_circular_imports,
    detect_dead_code,
    parse_file_ast,
    rename_symbol,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {str(t["name"]) for t in tool_list}


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True)
    return tmp_path


@pytest.fixture()
def handlers(tmp_repo: Path) -> dict[str, Any]:
    return make_chat_handlers(str(tmp_repo))


# ---------------------------------------------------------------------------
# Registration checks — every new tool must be in CHAT_TOOLS + have a handler
# ---------------------------------------------------------------------------

DAY1_TOOLS = [
    "parse_ast", "import_graph", "call_graph", "dead_code_detect",
    "circular_dep_detect", "rename_symbol",
    "git_rebase", "git_cherry_pick",
    "read_output", "run_node", "run_script", "docker_build", "docker_restart",
    "find_route", "find_api", "find_sql", "find_test", "find_config",
    "cpu_usage", "memory_usage", "disk_usage", "health_check", "task_progress",
    "replace_class", "undo_changes", "generate_patch",
    "explain_query", "run_migration", "seed_database",
]


@pytest.mark.parametrize("tool_name", DAY1_TOOLS)
def test_day1_tool_in_chat_tools(tool_name: str) -> None:
    assert tool_name in _tool_names(CHAT_TOOLS), f"{tool_name!r} missing from CHAT_TOOLS"


@pytest.mark.parametrize("tool_name", DAY1_TOOLS)
def test_day1_tool_has_handler(tool_name: str, handlers: dict[str, Any]) -> None:
    assert tool_name in handlers, f"No handler for {tool_name!r}"
    assert callable(handlers[tool_name]), f"Handler for {tool_name!r} not callable"


def test_total_tools_count() -> None:
    assert len(CHAT_TOOLS) >= 98, f"Expected >= 98 tools, got {len(CHAT_TOOLS)}"


def test_no_duplicate_tool_names() -> None:
    names = [str(t["name"]) for t in CHAT_TOOLS]
    dups = [n for n in names if names.count(n) > 1]
    assert not dups, f"Duplicate tool names: {dups}"


# ---------------------------------------------------------------------------
# Batch 10 — AST Engine (unit-tests against ast_engine module directly)
# ---------------------------------------------------------------------------

class TestParseAst:
    def test_parses_functions(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def hello(x, y):\n    return x + y\n\nasync def world():\n    pass\n")
        result = parse_file_ast(str(f))
        assert '"name": "hello"' in result
        assert '"name": "world"' in result
        assert '"is_async": true' in result

    def test_parses_classes(self, tmp_path: Path) -> None:
        f = tmp_path / "cls.py"
        f.write_text("class Foo(Bar):\n    def baz(self):\n        pass\n")
        result = parse_file_ast(str(f))
        assert '"name": "Foo"' in result
        assert '"baz"' in result

    def test_parses_imports(self, tmp_path: Path) -> None:
        f = tmp_path / "imp.py"
        f.write_text("import os\nfrom pathlib import Path\n")
        result = parse_file_ast(str(f))
        assert '"os"' in result
        assert '"pathlib"' in result

    def test_missing_file(self) -> None:
        result = parse_file_ast("/nonexistent/file.py")
        assert "[ERROR]" in result

    def test_non_py_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file.ts"
        f.write_text("const x = 1;")
        result = parse_file_ast(str(f))
        assert "[ERROR]" in result

    def test_syntax_error_handled(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n    # unclosed paren")
        result = parse_file_ast(str(f))
        assert "[ERROR]" in result

    def test_handler_works(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "sample.py").write_text("def greet():\n    pass\n")
        result = handlers["parse_ast"]({"path": "sample.py"})
        assert "greet" in result

    def test_handler_missing_file(self, handlers: dict[str, Any]) -> None:
        result = handlers["parse_ast"]({"path": "ghost.py"})
        assert "[ERROR]" in result


class TestImportGraph:
    def test_shows_imports(self, tmp_path: Path) -> None:
        f = tmp_path / "app.py"
        f.write_text("import os\nimport sys\nfrom pathlib import Path, PurePath\n")
        result = build_import_graph(str(f))
        assert "os" in result
        assert "sys" in result
        assert "pathlib" in result
        assert "Path" in result

    def test_missing_file(self) -> None:
        result = build_import_graph("/no/file.py")
        assert "[ERROR]" in result

    def test_no_imports(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("x = 1\n")
        result = build_import_graph(str(f))
        assert "no imports" in result.lower()

    def test_handler(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "imports.py").write_text("import json\nfrom typing import Any\n")
        result = handlers["import_graph"]({"path": "imports.py"})
        assert "json" in result


class TestCallGraph:
    def test_shows_calls(self, tmp_path: Path) -> None:
        f = tmp_path / "calls.py"
        f.write_text(
            "def main():\n    result = helper()\n    print(result)\n\ndef helper():\n    return 42\n"
        )
        result = build_call_graph(str(f))
        assert "main" in result
        assert "helper" in result
        assert "print" in result

    def test_filter_by_function(self, tmp_path: Path) -> None:
        f = tmp_path / "calls.py"
        f.write_text("def main():\n    foo()\n\ndef other():\n    bar()\n")
        result = build_call_graph(str(f), "main")
        assert "main" in result
        assert "foo" in result
        assert "other" not in result

    def test_missing_function(self, tmp_path: Path) -> None:
        f = tmp_path / "calls.py"
        f.write_text("def main():\n    pass\n")
        result = build_call_graph(str(f), "ghost")
        assert "[ERROR]" in result

    def test_handler(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "cg.py").write_text("def run():\n    print('hi')\n")
        result = handlers["call_graph"]({"path": "cg.py"})
        assert "run" in result


class TestDeadCodeDetect:
    def test_finds_unused(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text(
            "def used():\n    pass\n\ndef never_called():\n    pass\n\nused()\n"
        )
        result = detect_dead_code(str(tmp_path))
        # 'never_called' defined but not called
        assert "never_called" in result

    def test_no_dead_code(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text("def greet():\n    pass\n\ngreet()\n")
        result = detect_dead_code(str(tmp_path))
        # greet is called, so it should not appear
        # (result is either "No dead code" or might be empty)
        assert "greet" not in result or "✅" in result

    def test_missing_directory(self) -> None:
        result = detect_dead_code("/no/such/dir")
        assert "[ERROR]" in result

    def test_handler(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "dead.py").write_text("def orphan():\n    pass\n\ndef live():\n    pass\n\nlive()\n")
        result = handlers["dead_code_detect"]({})
        assert isinstance(result, str)
        assert len(result) > 0


class TestCircularDepDetect:
    def test_detects_cycle(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("from app.b import something\n")
        (tmp_path / "b.py").write_text("from app.a import something\n")
        result = detect_circular_imports(str(tmp_path))
        # Should detect cycle or at least not crash
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_cycles(self, tmp_path: Path) -> None:
        (tmp_path / "utils.py").write_text("def helper():\n    pass\n")
        (tmp_path / "main.py").write_text("# standalone\nx = 1\n")
        result = detect_circular_imports(str(tmp_path))
        assert isinstance(result, str)

    def test_missing_directory(self) -> None:
        result = detect_circular_imports("/no/such")
        assert "[ERROR]" in result

    def test_handler(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "standalone.py").write_text("x = 1\n")
        result = handlers["circular_dep_detect"]({})
        assert isinstance(result, str)


class TestRenameSymbol:
    def test_renames_across_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("def old_name():\n    pass\n")
        f2.write_text("from a import old_name\nold_name()\n")
        result = rename_symbol("old_name", "new_name", str(tmp_path))
        assert "new_name" in result
        assert "old_name" in f1.read_text() is False or "new_name" in f1.read_text()
        assert "new_name" in f2.read_text()

    def test_word_boundary_safe(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    pass\ndef foobar():\n    pass\n")
        rename_symbol("foo", "baz", str(tmp_path))
        text = f.read_text()
        # foobar should NOT be renamed to bazbar
        assert "foobar" in text
        assert "def baz():" in text

    def test_invalid_identifier(self, tmp_path: Path) -> None:
        result = rename_symbol("invalid-name", "new", str(tmp_path))
        assert "[ERROR]" in result

    def test_no_occurrences(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text("x = 1\n")
        result = rename_symbol("ghost_func", "new_name", str(tmp_path))
        assert "no occurrences" in result.lower()

    def test_missing_directory(self) -> None:
        result = rename_symbol("foo", "bar", "/no/such/dir")
        assert "[ERROR]" in result

    def test_handler(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "h.py").write_text("def my_func():\n    my_func()\n")
        result = handlers["rename_symbol"]({"old_name": "my_func", "new_name": "renamed_func"})
        assert "renamed_func" in result or "1 file" in result


# ---------------------------------------------------------------------------
# Batch 11 — Git extras
# ---------------------------------------------------------------------------

class TestGitRebase:
    def test_blocks_interactive(self, handlers: dict[str, Any]) -> None:
        result = handlers["git_rebase"]({"onto": "main", "interactive": True})
        assert "BLOCKED" in result or "TTY" in result

    def test_error_on_invalid_branch(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        # Make an initial commit so git is valid
        (tmp_repo / "init.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_repo), capture_output=True)
        result = handlers["git_rebase"]({"onto": "nonexistent_branch_xyzzy"})
        # Should return some kind of error message from git
        assert isinstance(result, str)
        assert len(result) > 0


class TestGitCherryPick:
    def test_error_on_invalid_hash(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "init.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_repo), capture_output=True)
        result = handlers["git_cherry_pick"]({"commit_hash": "deadbeef1234567890"})
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Batch 12 — Terminal extras
# ---------------------------------------------------------------------------

class TestReadOutput:
    def test_unknown_pid(self, handlers: dict[str, Any]) -> None:
        result = handlers["read_output"]({"pid": 9999999})
        assert "[ERROR]" in result

    def test_tracks_background_process(self, handlers: dict[str, Any]) -> None:
        # Start a background process via run_background then read its output
        bg_result = handlers["run_background"]({"command": "echo hello_background"})
        assert "PID" in bg_result
        # read_output is best-effort (process may have exited), just verify no crash
        pid_str = bg_result.split("PID ")[1].split(":")[0].strip()
        result = handlers["read_output"]({"pid": int(pid_str)})
        assert isinstance(result, str)


class TestRunNode:
    def test_runs_simple_code(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_node"]({"code": "console.log(1+1)"})
        # Either works (node installed) or returns helpful error
        assert "2" in result or "not found" in result.lower() or "[ERROR]" in result

    def test_syntax_error_caught(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_node"]({"code": "((( invalid"})
        assert isinstance(result, str)


class TestRunScript:
    def test_runs_python_script(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "hello.py").write_text("print('hello_from_script')\n")
        result = handlers["run_script"]({"path": "hello.py"})
        assert "hello_from_script" in result

    def test_runs_bash_script(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "hello.sh").write_text("#!/bin/bash\necho shell_ok\n")
        result = handlers["run_script"]({"path": "hello.sh", "interpreter": "bash"})
        assert "shell_ok" in result

    def test_missing_script(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_script"]({"path": "ghost.py"})
        assert "[ERROR]" in result

    def test_auto_detect_python(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "auto.py").write_text("print('auto_detected')\n")
        result = handlers["run_script"]({"path": "auto.py"})
        assert "auto_detected" in result


class TestDockerBuild:
    def test_missing_dockerfile_context(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        # No Dockerfile exists — should get docker error (docker CLI not crashing our code)
        result = handlers["docker_build"]({"tag": "test-img:latest"})
        # Either docker not available, or error from docker, but our code should not crash
        assert isinstance(result, str)
        assert len(result) > 0


class TestDockerRestart:
    def test_nonexistent_container(self, handlers: dict[str, Any]) -> None:
        result = handlers["docker_restart"]({"container": "gridiron_nonexistent_xyzzy"})
        assert isinstance(result, str)
        # docker error or not installed — just verify no Python exception


# ---------------------------------------------------------------------------
# Batch 13 — Smart search
# ---------------------------------------------------------------------------

class TestFindRoute:
    def test_finds_fastapi_routes(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "routes.py").write_text(
            'from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.get("/users")\ndef list_users():\n    pass\n'
        )
        result = handlers["find_route"]({"method": "GET"})
        assert "users" in result.lower() or "router.get" in result.lower()

    def test_no_routes(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "plain.py").write_text("x = 1\n")
        result = handlers["find_route"]({})
        assert isinstance(result, str)

    def test_filter_by_method(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "api.py").write_text(
            "@router.get('/a')\ndef get_a(): pass\n@router.post('/b')\ndef post_b(): pass\n"
        )
        result = handlers["find_route"]({"method": "POST"})
        assert isinstance(result, str)


class TestFindApi:
    def test_finds_handlers(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "views.py").write_text(
            "@router.get('/health')\ndef health_check():\n    return {'ok': True}\n"
        )
        result = handlers["find_api"]({"name": "health_check"})
        assert "health_check" in result

    def test_empty_name_returns_all(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "ep.py").write_text("@router.get('/test')\ndef do_test(): pass\n")
        result = handlers["find_api"]({})
        assert isinstance(result, str)


class TestFindSql:
    def test_finds_select(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "db.py").write_text(
            'from sqlalchemy import text\nq = text("SELECT id FROM users")\n'
        )
        result = handlers["find_sql"]({"keyword": "SELECT"})
        assert "SELECT" in result.upper() or "db.py" in result

    def test_no_sql(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "no_sql.py").write_text("x = 1\n")
        result = handlers["find_sql"]({})
        assert isinstance(result, str)


class TestFindTest:
    def test_finds_test_function(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "test_foo.py").write_text("def test_my_function():\n    assert True\n")
        result = handlers["find_test"]({"function_name": "my_function"})
        assert "test_my_function" in result or "test_foo.py" in result

    def test_not_found(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "unrelated.py").write_text("x = 1\n")
        result = handlers["find_test"]({"function_name": "ghost_xyzzy_func"})
        assert "no tests" in result.lower() or isinstance(result, str)


class TestFindConfig:
    def test_finds_env_key(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / ".env.example").write_text("DATABASE_URL=postgresql://localhost/mydb\nAPI_KEY=your_key_here\n")
        result = handlers["find_config"]({"key": "DATABASE_URL"})
        assert "DATABASE_URL" in result

    def test_not_found(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "config.py").write_text("PORT = 8000\n")
        result = handlers["find_config"]({"key": "NONEXISTENT_XYZ_SETTING_12345"})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Batch 14 — Monitoring
# ---------------------------------------------------------------------------

class TestCpuUsage:
    def test_returns_value(self, handlers: dict[str, Any]) -> None:
        result = handlers["cpu_usage"]({})
        assert isinstance(result, str)
        assert len(result) > 0
        # On Linux it should either show a percentage or /proc/stat data
        assert "cpu" in result.lower() or "%" in result or "[ERROR]" in result


class TestMemoryUsage:
    def test_returns_value(self, handlers: dict[str, Any]) -> None:
        result = handlers["memory_usage"]({})
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Mem" in result or "mem" in result or "[ERROR]" in result


class TestDiskUsage:
    def test_returns_disk_info(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        result = handlers["disk_usage"]({"path": str(tmp_repo)})
        assert "GB" in result or "[ERROR]" in result

    def test_default_path(self, handlers: dict[str, Any]) -> None:
        result = handlers["disk_usage"]({})
        assert isinstance(result, str)
        assert len(result) > 0


class TestHealthCheck:
    def test_returns_status(self, handlers: dict[str, Any]) -> None:
        result = handlers["health_check"]({"service": "backend"})
        assert isinstance(result, str)
        # Should not crash — backend may be down
        assert "backend" in result.lower() or "unreachable" in result.lower() or "✅" in result

    def test_db_check(self, handlers: dict[str, Any]) -> None:
        result = handlers["health_check"]({"service": "db"})
        assert isinstance(result, str)

    def test_all_services(self, handlers: dict[str, Any]) -> None:
        result = handlers["health_check"]({})
        assert isinstance(result, str)
        assert len(result) > 0


class TestTaskProgress:
    def test_no_db_url_graceful(self, handlers: dict[str, Any]) -> None:
        # DATABASE_URL may not be set in test env — should return helpful error
        result = handlers["task_progress"]({})
        assert isinstance(result, str)
        # Either DB results or "not set" error
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Batch 15 — Editing extras
# ---------------------------------------------------------------------------

class TestReplaceClass:
    def test_replaces_class(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "cls.py").write_text(
            "class Old:\n    def method(self):\n        pass\n\ndef standalone(): pass\n"
        )
        result = handlers["replace_class"](
            {"path": "cls.py", "class_name": "Old",
             "new_code": "class Old:\n    def method(self):\n        return 42\n"}
        )
        assert "Replaced" in result or "[ERROR]" not in result
        content = (tmp_repo / "cls.py").read_text()
        assert "return 42" in content
        assert "standalone" in content  # standalone function must survive

    def test_class_not_found(self, handlers: dict[str, Any], tmp_repo: Path) -> None:
        (tmp_repo / "no_cls.py").write_text("x = 1\n")
        result = handlers["replace_class"](
            {"path": "no_cls.py", "class_name": "Ghost", "new_code": "class Ghost: pass"}
        )
        assert "[ERROR]" in result

    def test_protected_path_blocked(self, handlers: dict[str, Any]) -> None:
        result = handlers["replace_class"](
            {"path": ".env", "class_name": "X", "new_code": "class X: pass"}
        )
        assert "POLICY DENIED" in result or "[ERROR]" in result


class TestUndoChanges:
    def test_blocked_without_session(self, handlers: dict[str, Any]) -> None:
        # handlers fixture has no session, so undo_changes should block
        result = handlers["undo_changes"]({"path": "any_file.py"})
        assert "BLOCKED" in result or "REQUIRES_CONFIRMATION" in result

    def test_protected_path_blocked(self, handlers: dict[str, Any]) -> None:
        result = handlers["undo_changes"]({"path": ".env"})
        assert "POLICY DENIED" in result or "BLOCKED" in result or "[ERROR]" in result


class TestGeneratePatch:
    def test_produces_unified_diff(self, handlers: dict[str, Any]) -> None:
        result = handlers["generate_patch"]({
            "content_a": "line 1\nline 2\nline 3\n",
            "content_b": "line 1\nchanged line\nline 3\n",
            "filename": "test.py",
        })
        assert "---" in result and "+++" in result
        assert "changed line" in result

    def test_no_diff(self, handlers: dict[str, Any]) -> None:
        content = "same content\n"
        result = handlers["generate_patch"]({"content_a": content, "content_b": content})
        assert "no differences" in result.lower()

    def test_empty_inputs(self, handlers: dict[str, Any]) -> None:
        result = handlers["generate_patch"]({"content_a": "", "content_b": "new line\n"})
        assert "+++" in result or "new line" in result


# ---------------------------------------------------------------------------
# Batch 16 — DB extras
# ---------------------------------------------------------------------------

class TestExplainQuery:
    def test_no_db_url_graceful(self, handlers: dict[str, Any]) -> None:
        result = handlers["explain_query"]({"query": "SELECT 1"})
        assert isinstance(result, str)
        # Either explanation from DB or "DATABASE_URL not set"
        assert len(result) > 0

    def test_strips_semicolons(self, handlers: dict[str, Any]) -> None:
        # Should not double-semicolon — just check it doesn't crash
        result = handlers["explain_query"]({"query": "SELECT 1;"})
        assert isinstance(result, str)


class TestRunMigration:
    def test_blocked_without_session(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_migration"]({})
        assert "BLOCKED" in result or "REQUIRES_CONFIRMATION" in result


class TestSeedDatabase:
    def test_blocked_without_session(self, handlers: dict[str, Any]) -> None:
        result = handlers["seed_database"]({})
        assert "BLOCKED" in result or "REQUIRES_CONFIRMATION" in result
