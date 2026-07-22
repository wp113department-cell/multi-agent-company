"""Frontend Developer Agent — implements UI changes in an isolated worktree.

Session 2 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph() inside the static-check retry loop.
- Added AGENT_CONTRACT (risk_level: medium — writes to worktree, executes tsc).
- Registered in capability_registry at module level.
- External interface (run_frontend_dev signature + return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
Static-check retry loop kept because tsc --noEmit runs OUTSIDE the LLM graph.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import CODER_TOOLS, make_coder_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "frontend_dev",
    "description": "Implements TypeScript/Next.js UI changes in an isolated worktree.",
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
    "input_types": ["task_id", "subtask_id", "plan", "worktree_path", "repo_path"],
    "output_types": ["files_changed"],
    "side_effects": ["write_files", "execute_bash"],
    "permissions": ["read_repo", "write_worktree", "execute_bash"],
    "risk_level": "medium",
    "expected_verification": {"checks_run": "tsc --noEmit executed before submit"},
    "dependencies": ["planner"],
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


def _run_frontend_checks(worktree_path: str) -> str | None:
    """Run tsc --noEmit in the apps/web directory. Returns error output or None on success."""
    web_dir = f"{worktree_path}/apps/web"
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd=web_dir,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        return (result.stdout + result.stderr)[:3000]
    return None


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------


def run_frontend_dev(
    task_id: int,
    subtask_id: int,
    plan: str,
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
    images: list[dict[str, str]] | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], str | None]:
    """Run frontend developer agent with static-check retry loop.

    Returns (files_changed, error). error is None on success.

    images (Day 16): optional reference images (e.g. a website design
    screenshot) — build the UI to match what they show.
    extra_env (Day 17): custom secrets merged into the bash tool's
    subprocess env.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries
    check_error: str | None = None
    image_note = (
        f"\n\n{len(images)} reference image(s) are attached below — build the "
        "UI to match what they show exactly."
        if images
        else ""
    )

    for attempt in range(max_retries):
        handlers = make_coder_handlers(worktree_path, repo, extra_env=extra_env)

        base_msg = (
            f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
            f"Frontend Implementation Plan:\n{plan}"
            f"{image_note}\n\n"
            "You are a frontend developer. Implement the plan in apps/web/.\n"
            "Use TypeScript strict mode. API calls go through apps/web/lib/api.ts.\n"
            "When done, call submit_patch with the list of files changed."
        )
        if attempt > 0 and check_error:
            base_msg += (
                f"\n\n[SELF-CORRECTION ATTEMPT {attempt}] "
                f"Previous attempt failed TypeScript typecheck:\n{check_error}\n"
                "Fix all type errors before submitting."
            )

        try:
            final_state = run_agent_graph(
                role_name="frontend_dev",
                model=settings.model_coder,
                tools=CODER_TOOLS,
                tool_handlers=handlers,
                verification_cfg=_VERIFICATION_CFG,
                initial_message=base_msg,
                task_description=f"Frontend implementation — subtask {subtask_id}",
                repo_path=repo,
                model_haiku=settings.model_router,
                enable_planning=True,
                enable_memory=True,
                enable_reflection=True,
                enable_lesson=True,
                max_turns=30,
                images=images,
            )
        except Exception as exc:
            logger.exception(
                "Frontend dev agent failed on attempt %d for subtask %d",
                attempt + 1,
                subtask_id,
            )
            if attempt == max_retries - 1:
                return [], f"Frontend dev agent error: {exc}"
            continue

        patch_result = handlers.get("_patch_result", {})
        files_changed: list[str] = patch_result.get("files_changed", [])

        if not final_state.get("submitted"):
            logger.warning("Frontend dev did not submit on attempt %d", attempt + 1)
            if attempt == max_retries - 1:
                return [], "Frontend dev did not submit a patch"
            continue

        check_error = _run_frontend_checks(worktree_path)
        if check_error is None:
            logger.info(
                "Frontend dev done — subtask %d, attempt %d, %d files, in=%d out=%d",
                subtask_id,
                attempt + 1,
                len(files_changed),
                final_state.get("tokens_in", 0),
                final_state.get("tokens_out", 0),
            )
            return files_changed, None

        logger.warning(
            "Frontend dev typecheck failed on attempt %d: %s",
            attempt + 1,
            check_error[:200],
        )
        if attempt == max_retries - 1:
            return (
                [],
                f"TypeScript errors persist after {max_retries} attempts:\n{check_error}",
            )

    return [], f"Frontend dev blocked after {max_retries} attempts"


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
                capabilities=["frontend_development", "typescript_coding"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("frontend_dev")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
