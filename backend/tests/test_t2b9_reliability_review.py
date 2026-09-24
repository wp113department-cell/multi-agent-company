"""T2-B9 (2026-09-24, GRIDIRON_PARTIAL #149 "Reliability Engineering /
Maintainability (beyond lint gates)").

app/repo_tools/reliability_review.py::find_unguarded_external_calls() is a
real, stdlib-only AST scan for external-I/O calls (HTTP, subprocess, a raw
DB execute, the Anthropic client) with no enclosing try/except anywhere in
their own function. Deliberately does NOT attempt a second "missing
retry/circuit-breaker" heuristic (see that module's own docstring for why
— the same "don't fabricate a fragile heuristic" discipline this
codebase's #297 precedent already established).

Real files on disk, real AST parsing — nothing mocked.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.tools import ARCH_REVIEWER_TOOLS, make_arch_reviewer_handlers
from app.repo_tools.reliability_review import (
    find_unguarded_external_calls,
    format_reliability_report,
)
from app.tools.filesystem.scan_reliability import SCAN_RELIABILITY_TOOL


def test_tool_registered_and_wired_into_architecture_reviewer() -> None:
    assert SCAN_RELIABILITY_TOOL["name"] == "scan_reliability"
    names = [t["name"] for t in ARCH_REVIEWER_TOOLS]
    assert "scan_reliability" in names


def test_handler_present_in_arch_reviewer_handlers(tmp_path: Path) -> None:
    handlers = make_arch_reviewer_handlers(str(tmp_path))
    assert "scan_reliability" in handlers


class TestFindUnguardedExternalCalls:
    def test_flags_a_real_unguarded_http_call(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text(
            "import requests\n\n"
            "def fetch():\n"
            "    return requests.get('http://x')\n"
        )
        report = find_unguarded_external_calls(str(tmp_path))
        assert len(report.findings) == 1
        assert report.findings[0].function == "fetch"
        assert report.findings[0].call == "requests.get"

    def test_does_not_flag_a_call_wrapped_in_try_except(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text(
            "import requests\n\n"
            "def fetch():\n"
            "    try:\n"
            "        return requests.get('http://x')\n"
            "    except Exception:\n"
            "        return None\n"
        )
        report = find_unguarded_external_calls(str(tmp_path))
        assert report.findings == []

    def test_does_not_flag_an_unrelated_dict_get_call(self, tmp_path: Path) -> None:
        # Bare `.get(...)` on an arbitrary object must never match — only
        # a real >=2-segment dotted tail (e.g. "requests.get") counts.
        (tmp_path / "a.py").write_text("def f(d):\n" "    return d.get('key')\n")
        report = find_unguarded_external_calls(str(tmp_path))
        assert report.findings == []

    def test_flags_subprocess_and_db_execute_calls(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text(
            "import subprocess\n\n"
            "def run_cmd():\n"
            "    return subprocess.run(['ls'])\n\n"
            "async def query(db):\n"
            "    return await db.execute('select 1')\n"
        )
        report = find_unguarded_external_calls(str(tmp_path))
        calls = {(f.function, f.call) for f in report.findings}
        assert ("run_cmd", "subprocess.run") in calls
        assert ("query", "db.execute") in calls

    def test_a_call_guarded_only_by_an_unrelated_sibling_try_is_still_flagged(
        self, tmp_path: Path
    ) -> None:
        # The try/except in this function protects a DIFFERENT statement —
        # the requests.get call itself is NOT inside any try body, so it
        # must still be flagged (a real, honest positive, not swallowed by
        # the mere presence of SOME try somewhere in the function).
        (tmp_path / "a.py").write_text(
            "import requests\n\n"
            "def fetch():\n"
            "    try:\n"
            "        x = 1 / 0\n"
            "    except ZeroDivisionError:\n"
            "        pass\n"
            "    return requests.get('http://x')\n"
        )
        report = find_unguarded_external_calls(str(tmp_path))
        assert len(report.findings) == 1
        assert report.findings[0].call == "requests.get"

    def test_nested_function_is_evaluated_independently(self, tmp_path: Path) -> None:
        # The outer function's own try wraps only the CALL to inner(), not
        # inner's own body — inner's unguarded requests.get is a real,
        # separate finding (see the module's own documented limitation:
        # a try several frames up the real call stack is invisible to a
        # per-function static scan).
        (tmp_path / "a.py").write_text(
            "import requests\n\n"
            "def outer():\n"
            "    def inner():\n"
            "        return requests.get('http://x')\n"
            "    try:\n"
            "        return inner()\n"
            "    except Exception:\n"
            "        return None\n"
        )
        report = find_unguarded_external_calls(str(tmp_path))
        assert len(report.findings) == 1
        assert report.findings[0].function == "inner"

    def test_no_findings_reports_a_clean_message(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def f():\n    return 1\n")
        report = find_unguarded_external_calls(str(tmp_path))
        assert report.findings == []
        assert "No unguarded external calls" in format_reliability_report(report)

    def test_nonexistent_directory_returns_an_empty_report(
        self, tmp_path: Path
    ) -> None:
        report = find_unguarded_external_calls(str(tmp_path / "does_not_exist"))
        assert report.findings == []
        assert report.files_scanned == 0


class TestScanReliabilityHandler:
    def test_handler_reports_a_real_finding_through_the_full_tool_path(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "risky.py").write_text(
            "import requests\n\ndef f():\n    return requests.get('http://x')\n"
        )
        handlers = make_arch_reviewer_handlers(str(tmp_path))
        result = handlers["scan_reliability"]({})
        assert "requests.get" in result
        assert "risky.py" in result

    def test_handler_rejects_a_directory_outside_the_worktree(
        self, tmp_path: Path
    ) -> None:
        handlers = make_arch_reviewer_handlers(str(tmp_path))
        result = handlers["scan_reliability"]({"directory": "../../../etc"})
        assert "[POLICY DENIED]" in result
