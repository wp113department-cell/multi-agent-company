"""Gap-closure Stage 1.7 (answers.md) — proves scripts/ci_tech_debt_scan.py's
skip/trigger logic and summary formatting are correct, without incurring a
real Anthropic API call: run_tech_debt_agent is mocked at the call site for
every test that reaches it.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from scripts.ci_tech_debt_scan import format_summary, get_changed_files, main


class TestGetChangedFiles:
    def test_returns_parsed_lines_on_success(self) -> None:
        fake = MagicMock(
            returncode=0,
            stdout="backend/app/config.py\napps/web/app/page.tsx\n",
        )
        with patch("scripts.ci_tech_debt_scan.subprocess.run", return_value=fake):
            assert get_changed_files("origin/main") == [
                "backend/app/config.py",
                "apps/web/app/page.tsx",
            ]

    def test_returns_empty_list_when_git_diff_fails(self) -> None:
        fake = MagicMock(returncode=1, stdout="")
        with patch("scripts.ci_tech_debt_scan.subprocess.run", return_value=fake):
            assert get_changed_files("origin/main") == []

    def test_returns_empty_list_when_git_raises(self) -> None:
        with patch(
            "scripts.ci_tech_debt_scan.subprocess.run",
            side_effect=subprocess.SubprocessError("boom"),
        ):
            try:
                get_changed_files("origin/main")
                raised = False
            except subprocess.SubprocessError:
                raised = True
        # get_changed_files does not itself catch SubprocessError — this
        # documents that main()'s own try/except is what protects the build,
        # not get_changed_files.
        assert raised is True


class TestFormatSummary:
    def test_reports_no_debt_items(self) -> None:
        out = format_summary([], [], "")
        assert "No debt items reported." in out

    def test_formats_dict_findings_with_file_line_severity(self) -> None:
        out = format_summary(
            [
                {
                    "file": "app/x.py",
                    "line": 12,
                    "severity": "high",
                    "description": "dupe logic",
                }
            ],
            ["refactor x.py"],
            "2 days",
        )
        assert "app/x.py:12" in out
        assert "[high]" in out
        assert "dupe logic" in out
        assert "refactor x.py" in out
        assert "2 days" in out

    def test_formats_plain_string_findings(self) -> None:
        out = format_summary(["some finding"], [], "")
        assert "some finding" in out

    def test_always_includes_non_blocking_notice(self) -> None:
        out = format_summary([], [], "")
        assert "does not block the merge" in out


class TestMain:
    def test_skips_when_no_base_ref(self, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
        with patch("scripts.ci_tech_debt_scan.run_tech_debt_agent") as mock_run:
            assert main() == 0
            mock_run.assert_not_called()

    def test_skips_when_no_structural_files_changed(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        with patch(
            "scripts.ci_tech_debt_scan.get_changed_files",
            return_value=["README.md"],
        ), patch("scripts.ci_tech_debt_scan.run_tech_debt_agent") as mock_run:
            assert main() == 0
            mock_run.assert_not_called()

    def test_skips_when_structural_but_no_api_key(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch(
            "scripts.ci_tech_debt_scan.get_changed_files",
            return_value=["backend/app/config.py"],
        ), patch("scripts.ci_tech_debt_scan.run_tech_debt_agent") as mock_run:
            assert main() == 0
            mock_run.assert_not_called()

    def test_runs_tech_debt_agent_and_writes_summary_when_triggered(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
        summary_file = tmp_path / "step_summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        fake_result = MagicMock(
            findings=[
                {"file": "a.py", "line": 1, "severity": "low", "description": "d"}
            ],
            raw={"priority_fixes": ["fix a"], "effort_estimate": "1 day"},
        )
        with patch(
            "scripts.ci_tech_debt_scan.get_changed_files",
            return_value=["backend/app/config.py"],
        ), patch(
            "scripts.ci_tech_debt_scan.run_tech_debt_agent", return_value=fake_result
        ) as mock_run:
            assert main() == 0
            mock_run.assert_called_once()

        written = summary_file.read_text(encoding="utf-8")
        assert "1 debt item(s) found" in written
        assert "fix a" in written
        assert "1 day" in written

    def test_never_fails_build_when_tech_debt_agent_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        with patch(
            "scripts.ci_tech_debt_scan.get_changed_files",
            return_value=["backend/app/config.py"],
        ), patch(
            "scripts.ci_tech_debt_scan.run_tech_debt_agent",
            side_effect=RuntimeError("API down"),
        ):
            assert main() == 0
