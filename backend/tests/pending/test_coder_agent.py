"""Coder Agent live tests — require ANTHROPIC_API_KEY.

Live-AI plan (PENDING_TESTS_API_KEYS.md §N): "writes a file" and "passes
ruff" share one real coder run, and repo_path is the small temp project the
coder writes into (not this whole repository) to keep the prompt small.
"""

from __future__ import annotations

from pathlib import Path

import os
import subprocess
import sys
import textwrap
from typing import Any

import pytest
from tests.pending.conftest import requires_anthropic

_REPO_ROOT = str(Path(__file__).resolve().parents[3])  # repo root, not a machine path

_THIS_REPO = _REPO_ROOT


def _create_temp_worktree(tmp_path: pytest.TempPathFactory) -> str:
    """Create a minimal Python project in tmp_path for the coder to write into."""
    wt = str(tmp_path)
    # Create a simple Python package so mypy/ruff have something to check
    pkg = os.path.join(wt, "mypackage")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w") as f:
        f.write("")
    with open(os.path.join(wt, "pyproject.toml"), "w") as f:
        f.write("[tool.mypy]\npython_version = '3.11'\n")
    return wt


@pytest.fixture(scope="module")
def coder_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from app.agents.coder import run_coder

    worktree = _create_temp_worktree(tmp_path_factory.mktemp("coder_wt"))  # type: ignore[arg-type]
    plan = textwrap.dedent("""\
        ## Task
        Create a file `mypackage/hello.py` that contains a single function
        `greet(name: str) -> str` returning f"Hello, {name}!".

        ## Files To Inspect
        - mypackage/__init__.py

        ## Implementation Steps
        1. Create `mypackage/hello.py` with the `greet` function.

        ## Test Strategy
        Function can be imported and called.
    """)
    files_changed, error, *_ = run_coder(
        task_id=40, plan=plan, worktree_path=worktree, repo_path=worktree
    )
    return {"files": files_changed, "error": error, "worktree": worktree}


@requires_anthropic
class TestCoderAgent:
    """Coder Agent: approved plan → write files in worktree, pass mypy + ruff."""

    def test_coder_writes_file(self, coder_run: dict[str, Any]) -> None:
        assert coder_run["error"] is None, f"Coder failed: {coder_run['error']}"
        assert len(coder_run["files"]) >= 1, "Coder did not report any files changed"
        assert os.path.exists(
            os.path.join(coder_run["worktree"], "mypackage", "hello.py")
        )

    def test_coder_output_passes_ruff(self, coder_run: dict[str, Any]) -> None:
        assert coder_run["error"] is None, f"Coder failed: {coder_run['error']}"
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "."],
            cwd=coder_run["worktree"],
            capture_output=True,
            text=True,
        )
        assert (
            result.returncode == 0
        ), f"ruff found issues:\n{result.stdout}{result.stderr}"

    def test_coder_blocked_on_policy_violation(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Coder is blocked when the plan asks it to write to .env (policy deny)."""
        from app.agents.coder import run_coder

        worktree = _create_temp_worktree(tmp_path)
        plan = textwrap.dedent("""\
            ## Task
            Add ANTHROPIC_API_KEY=test to .env file.

            ## Files To Inspect
            - None

            ## Implementation Steps
            1. Write to .env

            ## Test Strategy
            .env contains the key.
        """)

        # The coder may still "succeed" from its own perspective (submit_patch),
        # but policy denials must appear in the logs. At minimum: coder should not
        # actually write to .env.
        _, _, *_ = run_coder(
            task_id=42, plan=plan, worktree_path=worktree, repo_path=worktree
        )

        dotenv_path = os.path.join(worktree, ".env")
        assert not os.path.exists(
            dotenv_path
        ), "CRITICAL: Policy engine allowed Coder to write to .env — policy is broken"
