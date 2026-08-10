"""Tests for AUDIT_Q_BATCH01 (Repository Execution, Terminal Intelligence,
Multi-Terminal, Coding Workflow, Multi-File Ops) remediation.

Covers: unified process_manager, run_background task-dependency chaining,
background hang detection, run_parallel_commands fan-out, sync_files,
token-based rename_symbol + large-batch safety cap, read_files pagination,
and structured pytest/mypy/ruff/tsc output parsing.

All tests run against real temp directories/processes, no mocks.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from app.agents.output_parsers import parse_diagnostic_summary, parse_pytest_summary
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.fleet import bg_process_registry, process_manager
from app.repo_tools.ast_engine import rename_symbol


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
# New tools registered
# ---------------------------------------------------------------------------


class TestNewToolsRegistered:
    def test_new_tools_in_chat_tools(self) -> None:
        names = _tool_names(CHAT_TOOLS)
        for expected in (
            "list_background_processes",
            "run_parallel_commands",
            "sync_files",
        ):
            assert expected in names

    def test_new_tools_have_handlers(self, handlers: dict[str, Any]) -> None:
        for key in (
            "list_background_processes",
            "run_parallel_commands",
            "sync_files",
        ):
            assert key in handlers

    def test_new_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for name in (
            "list_background_processes",
            "run_parallel_commands",
            "sync_files",
        ):
            assert name in TOOL_MANIFEST


# ---------------------------------------------------------------------------
# §1/§58 — unified process manager
# ---------------------------------------------------------------------------


class TestProcessManager:
    def test_spawn_kill_read_roundtrip(self, tmp_path: Path) -> None:
        procs: dict[int, Any] = {}
        msg = process_manager.spawn("echo hello_pm", str(tmp_path), procs)
        assert "Started background process PID" in msg
        pid = int(msg.split("PID ")[1].split(":")[0])
        assert pid in procs
        time.sleep(0.3)

        def _read_stream(stream: Any) -> str | None:
            return stream.read()

        out = process_manager.read_output(pid, 50, procs, _read_stream)
        assert "hello_pm" in out or "exited" in out

        kill_msg = process_manager.kill(pid, "TERM", procs)
        assert "Sent TERM" in kill_msg or "No process" in kill_msg
        assert pid not in procs

    def test_list_tracked_reports_age_and_hung_flag(self, tmp_path: Path) -> None:
        procs: dict[int, Any] = {}
        process_manager.spawn("sleep 0.2", str(tmp_path), procs)
        entries = process_manager.list_tracked(procs)
        assert len(entries) == 1
        assert entries[0]["alive"] is True
        assert entries[0]["possibly_hung"] is False
        rendered = process_manager.format_tracked(procs)
        assert "PID" in rendered
        for pid in list(procs):
            process_manager.kill(pid, "KILL", procs)

    def test_run_background_and_kill_still_work_via_handlers(
        self, handlers: dict[str, Any]
    ) -> None:
        result = handlers["run_background"]({"command": "sleep 5"})
        assert "Started background process PID" in result
        pid = int(result.split("PID ")[1].split(":")[0])
        listed = handlers["list_background_processes"]({})
        assert str(pid) in listed
        kill_result = handlers["kill_process"]({"pid": pid})
        assert "Sent TERM" in kill_result

    def test_run_background_wait_for_pids_dependency(self, tmp_path: Path) -> None:
        """AUDIT_Q_BATCH01 §58 'Task dependency handling between terminal jobs'."""
        procs: dict[int, Any] = {}
        dep_msg = process_manager.spawn("sleep 0.3", str(tmp_path), procs)
        dep_pid = int(dep_msg.split("PID ")[1].split(":")[0])

        marker = tmp_path / "dependent_ran.txt"
        dependent_msg = process_manager.spawn(
            f"touch {marker}", str(tmp_path), procs, wait_for_pids=[dep_pid]
        )
        assert "waiting on" in dependent_msg
        dependent_pid = int(dependent_msg.split("PID ")[1].split(" ")[0])

        # Marker must not exist immediately — the dependent command is still
        # waiting on dep_pid.
        assert not marker.exists()
        for _ in range(30):
            if not marker.exists():
                time.sleep(0.1)
            else:
                break
        assert marker.exists()
        for pid in (dep_pid, dependent_pid):
            process_manager.kill(pid, "KILL", procs)


class TestBgProcessHangDetection:
    def test_snapshot_and_hang_threshold_helpers(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from app.config import get_settings

        registry_path = tmp_path / "bg-registry.json"
        monkeypatch.setattr(
            get_settings(), "bg_process_registry_path", str(registry_path)
        )
        monkeypatch.setattr(get_settings(), "bg_process_hang_threshold_seconds", 0)

        bg_process_registry.register(999999, "sleep 100", str(tmp_path))
        snap = bg_process_registry.snapshot()
        assert "999999" in snap
        assert bg_process_registry.hang_threshold_seconds() == 0
        bg_process_registry.unregister(999999)
        assert "999999" not in bg_process_registry.snapshot()


# ---------------------------------------------------------------------------
# §58 — concurrent fan-out
# ---------------------------------------------------------------------------


class TestRunParallelCommands:
    def test_runs_commands_concurrently(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_parallel_commands"](
            {"commands": [{"command": "echo one"}, {"command": "echo two"}]}
        )
        assert "one" in result
        assert "two" in result

    def test_rejects_too_many_commands(self, handlers: dict[str, Any]) -> None:
        cmds = [{"command": "echo x"} for _ in range(11)]
        result = handlers["run_parallel_commands"]({"commands": cmds})
        assert "[ERROR]" in result

    def test_rejects_dangerous_subcommand(self, handlers: dict[str, Any]) -> None:
        result = handlers["run_parallel_commands"](
            {"commands": [{"command": "echo ok"}, {"command": "rm -rf /"}]}
        )
        assert "POLICY DENIED" in result


# ---------------------------------------------------------------------------
# §18 — sync_files
# ---------------------------------------------------------------------------


class TestSyncFiles:
    def test_creates_and_updates_targets(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "a.txt").write_text("hello")
        result = handlers["sync_files"]({"source": "a.txt", "paths": ["b.txt"]})
        assert "created" in result
        assert (tmp_repo / "b.txt").read_text() == "hello"

        # unchanged on second sync
        result2 = handlers["sync_files"]({"source": "a.txt", "paths": ["b.txt"]})
        assert "unchanged" in result2

        (tmp_repo / "a.txt").write_text("updated")
        result3 = handlers["sync_files"]({"source": "a.txt", "paths": ["b.txt"]})
        assert "updated" in result3
        assert (tmp_repo / "b.txt").read_text() == "updated"

    def test_missing_source(self, handlers: dict[str, Any]) -> None:
        result = handlers["sync_files"]({"source": "nope.txt", "paths": ["x.txt"]})
        assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# §18/§59 — token-based rename_symbol + safety cap
# ---------------------------------------------------------------------------


class TestRenameSymbolTokenAware:
    def test_skips_strings_and_comments(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text(
            "def old_name(x):\n"
            '    """calls old_name recursively"""\n'
            "    # old_name is called here\n"
            '    s = "old_name"\n'
            "    return old_name(x - 1) if x else s\n"
        )
        result = rename_symbol("old_name", "new_name", str(tmp_path))
        assert "Renamed" in result
        text = f.read_text()
        assert "def new_name(x):" in text
        assert "return new_name(x - 1)" in text
        # Untouched: docstring, comment, string literal
        assert '"""calls old_name recursively"""' in text
        assert "# old_name is called here" in text
        assert 's = "old_name"' in text

    def test_falls_back_to_regex_for_non_python_pattern(self, tmp_path: Path) -> None:
        f = tmp_path / "a.ts"
        f.write_text("const oldName = 1;\nconsole.log(oldName);\n")
        result = rename_symbol("oldName", "newName", str(tmp_path), file_pattern="*.ts")
        assert "Renamed" in result
        assert "newName" in f.read_text()

    def test_large_batch_returns_dry_run_preview(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "rename_symbol_max_files", 2)
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("def ghost():\n    pass\n")

        preview = rename_symbol("ghost", "renamed", str(tmp_path))
        assert "[DRY RUN]" in preview
        assert (tmp_path / "f0.py").read_text() == "def ghost():\n    pass\n"

        applied = rename_symbol(
            "ghost", "renamed", str(tmp_path), confirm_large_batch=True
        )
        assert "Renamed" in applied
        assert "def renamed():" in (tmp_path / "f0.py").read_text()

    def test_handler_passes_confirm_large_batch(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "h.py").write_text("def my_func():\n    my_func()\n")
        result = handlers["rename_symbol"](
            {
                "old_name": "my_func",
                "new_name": "renamed_func",
                "confirm_large_batch": True,
            }
        )
        assert "renamed_func" in result or "1 file" in result


# ---------------------------------------------------------------------------
# §59 — read_files pagination
# ---------------------------------------------------------------------------


class TestReadFilesPagination:
    def test_truncation_notice_and_offset(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        paths = []
        for i in range(25):
            name = f"f{i}.txt"
            (tmp_repo / name).write_text(f"content-{i}")
            paths.append(name)

        first = handlers["read_files"]({"paths": paths})
        assert "[NOTICE]" in first
        assert "offset=20" in first
        assert "content-0" in first
        assert "content-20" not in first

        second = handlers["read_files"]({"paths": paths, "offset": 20})
        assert "content-20" in second
        assert "content-24" in second
        assert "[NOTICE]" not in second

    def test_no_truncation_under_limit(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "one.txt").write_text("x")
        result = handlers["read_files"]({"paths": ["one.txt"]})
        assert "[NOTICE]" not in result


# ---------------------------------------------------------------------------
# §17 — structured test/lint output parsing
# ---------------------------------------------------------------------------


class TestOutputParsers:
    def test_parse_pytest_summary_mixed_results(self) -> None:
        raw = (
            "collected 5 items\n"
            "F.F..\n"
            "=================== 2 failed, 3 passed in 0.42s ===================\n"
        )
        summary = parse_pytest_summary(raw)
        assert summary is not None
        assert "2 failed" in summary
        assert "3 passed" in summary

    def test_parse_pytest_summary_no_match(self) -> None:
        assert parse_pytest_summary("random crash output, no summary line") is None

    def test_parse_mypy_summary(self) -> None:
        assert (
            parse_diagnostic_summary(
                "Found 3 errors in 2 files (checked 10 source files)", "mypy"
            )
            == "=== mypy Summary === 3 error(s) in 2 file(s)"
        )
        assert (
            parse_diagnostic_summary(
                "Success: no issues found in 10 source files", "mypy"
            )
            == "=== mypy Summary === 0 errors"
        )

    def test_parse_ruff_summary(self) -> None:
        assert (
            parse_diagnostic_summary("Found 5 errors.", "ruff")
            == "=== ruff Summary === 5 error(s)"
        )
        assert (
            parse_diagnostic_summary("All checks passed!", "ruff")
            == "=== ruff Summary === 0 errors"
        )

    def test_run_tests_handler_includes_summary(
        self, tmp_repo: Path, handlers: dict[str, Any]
    ) -> None:
        (tmp_repo / "test_sample.py").write_text(
            "def test_pass():\n    assert True\n\ndef test_fail():\n    assert False\n"
        )
        result = handlers["run_tests"]({"runner": "pytest"})
        assert "Test Summary" in result
