"""Coder Agent — implements an approved plan inside a git worktree, with self-correction loop.

Session 2 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph() inside the static-check retry loop.
- Added AGENT_CONTRACT (risk_level: medium — writes to worktree, executes bash).
- Registered in capability_registry at module level.
- External interface (run_coder signature + return type tuple[list[str], str|None, int, int]) unchanged.
- Token accumulation across retries preserved: total_in/total_out sum each attempt.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
Static-check retry loop kept because mypy/ruff run OUTSIDE the LLM graph.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import CODER_TOOLS, make_coder_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "coder",
    "description": "Implements an approved plan in a git worktree — generic backend/frontend capable.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "search_symbols",
        "get_file_tree",
        "git_log",
        "read_files",
        "file_exists",
        "file_info",
        "find_references",
        "find_todos",
        "search_imports",
        "git_status",
        "git_show",
        "git_blame",
        "analyze_file",
        "edit_file",
        "write_file",
        "git_diff",
        "bash",
        "submit_patch",
    ],
    "input_types": ["task_id", "plan", "worktree_path", "repo_path"],
    "output_types": ["files_changed", "tokens_in", "tokens_out"],
    "side_effects": ["write_files", "execute_bash"],
    "permissions": ["read_repo", "write_worktree", "execute_bash"],
    "risk_level": "medium",
    "expected_verification": {"checks_run": "bash mypy/ruff executed before submit"},
    "dependencies": [],
}

# ---------------------------------------------------------------------------
# Verification contract — resets checks when files change
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"bash": "checks_run", "git_diff": "diff_checked"},
    reset_by=("edit_file", "write_file"),
    reset_keys=("checks_run",),
    enforce_in_result={"checks_run": "checks_run"},
    initial={"checks_run": False, "diff_checked": False},
)

# ---------------------------------------------------------------------------
# Static checks — run OUTSIDE the LLM graph after submission
# ---------------------------------------------------------------------------


def _run_checks(worktree_path: str) -> str | None:
    """Run mypy + ruff in the worktree. Returns error output or None on success."""
    python = sys.executable
    checks = [
        [python, "-m", "mypy", ".", "--ignore-missing-imports", "--no-error-summary"],
        [python, "-m", "ruff", "check", "."],
    ]
    for cmd in checks:
        result = subprocess.run(
            cmd, cwd=worktree_path, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return (result.stdout + result.stderr)[:3000]
    return None


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------


def run_coder(
    task_id: int,
    plan: str,
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], str | None, int, int]:
    """Run coder agent with static-check retry loop.

    Returns (files_changed, error, tokens_in, tokens_out). error is None on success.
    Tokens are accumulated across all retry attempts.

    extra_env (Day 17): custom secrets merged into the bash tool's
    subprocess env.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries
    total_in = 0
    total_out = 0
    check_error: str | None = None

    for attempt in range(max_retries):
        handlers = make_coder_handlers(worktree_path, repo, extra_env=extra_env)

        base_msg = (
            f"Task ID: {task_id}\n\n"
            f"Approved Implementation Plan:\n{plan}\n\n"
            "Implement the plan exactly as described. "
            "When done, call submit_patch with the list of files you changed."
        )
        if attempt > 0 and check_error:
            base_msg += (
                f"\n\n[RETRY {attempt}] Previous attempt failed checks:\n{check_error}\n"
                "Fix the issues and try again."
            )

        try:
            final_state = run_agent_graph(
                role_name="coder",
                model=settings.model_coder,
                tools=CODER_TOOLS,
                tool_handlers=handlers,
                verification_cfg=_VERIFICATION_CFG,
                initial_message=base_msg,
                task_description=f"Code implementation — task {task_id}",
                repo_path=repo,
                model_haiku=settings.model_router,
                enable_planning=True,
                enable_memory=True,
                enable_reflection=True,
                enable_lesson=True,
                max_turns=30,
            )
            total_in += final_state.get("tokens_in", 0)
            total_out += final_state.get("tokens_out", 0)
        except Exception as exc:
            patch_result_check = handlers.get("_patch_result", {})
            if patch_result_check.get("files_changed"):
                # Patch submitted before the error (e.g. rate limit on follow-up turn) — treat as success.
                logger.warning("Coder error after patch submission (ignored): %s", exc)
            else:
                logger.exception("Coder agent failed on attempt %d", attempt + 1)
                if attempt == max_retries - 1:
                    return [], f"Coder agent error: {exc}", total_in, total_out
                continue

        patch_result = handlers.get("_patch_result", {})
        files_changed: list[str] = patch_result.get("files_changed", [])

        try:
            check_error = _run_checks(worktree_path)
        except Exception as exc:
            check_error = str(exc)

        if check_error is None:
            logger.info(
                "Coder done — attempt %d, %d files changed, tokens_in=%d tokens_out=%d",
                attempt + 1,
                len(files_changed),
                total_in,
                total_out,
            )
            return files_changed, None, total_in, total_out

        logger.warning(
            "Checks failed on attempt %d: %s", attempt + 1, check_error[:200]
        )
        if attempt == max_retries - 1:
            return (
                [],
                f"Checks still failing after {max_retries} attempts:\n{check_error}",
                total_in,
                total_out,
            )

    return [], f"Coder blocked after {max_retries} attempts", total_in, total_out


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=["code_implementation", "generic_coding"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("coder")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
