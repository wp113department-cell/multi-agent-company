"""#297 (2026-09-28, "Use documentation while coding automatically (no
explicit call)") — the audit's own IMPLEMENTATION PLAN's narrow trigger
("only fire when an import fails to resolve"), wired into manager.py's
per-subtask retry loop right after the dev agent's own diff is produced,
before commit/QA/review. Real broken-import file on disk (tmp_path), the
PyPI lookup itself mocked here (its own real-network correctness is
covered separately in test_doc_lookup.py).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from app.agents.qa import QAResult
from app.agents.reviewer import ReviewResult


def _run(worktree_path: str, backend_dev_side_effect: list) -> tuple[dict, object]:
    from app.agents.manager import run_manager

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
    ), patch(
        "app.services.git_service.git_add",
        return_value={"ok": True, "stdout": "", "stderr": ""},
    ), patch(
        "app.services.git_service.git_commit",
        return_value={"ok": True, "stdout": "", "stderr": ""},
    ), patch(
        "app.repo_tools.doc_lookup.lookup_package_doc_hint",
        return_value="PyPI hint: package not found, check for a typo.",
    ):
        mock_backend_dev.side_effect = backend_dev_side_effect
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=999_301,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=worktree_path,
                plan="plan",
                repo_path=worktree_path,
            )
        )
    return result, mock_backend_dev


def test_broken_import_blocks_after_retries_with_a_real_doc_hint_fed_back(
    tmp_path: Path,
) -> None:
    (tmp_path / "broken.py").write_text(
        "import totally_fake_module_xyz_never_real\n"
    )
    result, mock_backend_dev = _run(
        str(tmp_path),
        backend_dev_side_effect=[
            (["broken.py"], None, 0, 0),
            (["broken.py"], None, 0, 0),
        ],
    )

    assert mock_backend_dev.call_count == 2
    second_call_plan = mock_backend_dev.call_args_list[1].kwargs["plan"]
    assert "totally_fake_module_xyz_never_real" in second_call_plan
    assert "PyPI hint" in second_call_plan
    assert result["status"] == "blocked"
    assert result["results"][0]["status"] == "blocked"


def test_a_self_corrected_import_on_retry_completes_normally(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text(
        "import totally_fake_module_xyz_never_real\n"
    )

    call_count = {"n": 0}

    def _fix_on_second_call(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            (tmp_path / "broken.py").write_text("import os\n")
        return (["broken.py"], None, 0, 0)

    from app.agents.manager import run_manager

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
    ), patch(
        "app.services.git_service.git_add",
        return_value={"ok": True, "stdout": "", "stderr": ""},
    ), patch(
        "app.services.git_service.git_commit",
        return_value={"ok": True, "stdout": "", "stderr": ""},
    ), patch(
        "app.repo_tools.doc_lookup.lookup_package_doc_hint",
        return_value="PyPI hint: package not found, check for a typo.",
    ):
        mock_backend_dev.side_effect = _fix_on_second_call
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=999_302,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
            )
        )

    assert mock_backend_dev.call_count == 2
    mock_qa.assert_called_once()
    assert result["status"] == "completed"


def test_disabled_via_config_skips_the_check_entirely(tmp_path: Path) -> None:
    from app.agents.manager import run_manager
    from app.config import get_settings

    (tmp_path / "broken.py").write_text(
        "import totally_fake_module_xyz_never_real\n"
    )

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
    ), patch(
        "app.services.git_service.git_add",
        return_value={"ok": True, "stdout": "", "stderr": ""},
    ), patch(
        "app.services.git_service.git_commit",
        return_value={"ok": True, "stdout": "", "stderr": ""},
    ), patch(
        "app.repo_tools.code_hygiene.find_broken_imports_in_files"
    ) as mock_scan, patch.object(
        get_settings(), "enable_auto_doc_lookup_on_broken_import", False
    ):
        mock_backend_dev.return_value = (["broken.py"], None, 0, 0)
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=999_303,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
            )
        )

    mock_scan.assert_not_called()
    assert result["status"] == "completed"


def test_no_broken_imports_does_not_affect_normal_completion(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("import os\n")
    result, mock_backend_dev = _run(
        str(tmp_path), backend_dev_side_effect=[(["clean.py"], None, 0, 0)]
    )
    assert mock_backend_dev.call_count == 1
    assert result["status"] == "completed"
