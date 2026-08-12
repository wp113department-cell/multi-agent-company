"""Mobile Developer Agent — implements mobile app changes (React Native/Expo,
Flutter, native Android, native iOS) in an isolated worktree.

AUDIT_Q_BATCH17 §71 gap-closure (2026-08-12) — "Mobile Development (Android/
iOS/Flutter/React Native): NO — zero references anywhere — no agent, role
file, or tool." Mirrors backend_dev.py/frontend_dev.py's exact worktree+bash
coder pattern (same AGENT_CONTRACT shape, same static-check-outside-the-
graph retry loop) so mobile sits at the same capability tier as Backend/
Frontend rather than a downgraded advisory-only agent.

One deliberate difference from backend_dev/frontend_dev: those two each
hardcode ONE known, evidenced stack (this project's own Python backend /
Next.js frontend). No such fixed mobile stack exists anywhere in this repo,
so hardcoding e.g. "always run flutter analyze" would be inventing project
structure that isn't in evidence — exactly what Zero-Hallucination/Zero-
Hardcoding forbid. Instead, _run_mobile_checks() detects which real mobile
toolchain markers are actually present in the worktree (pubspec.yaml,
android/*.gradle*, ios/*.xcodeproj, react-native/expo in package.json) and
runs only the matching real command for whichever framework is actually
there. No recognized mobile project yet (e.g. this is the very first
scaffold) is not a failure — there is nothing to check against yet.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    CODER_TOOLS,
    make_coder_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "mobile_dev",
    "description": (
        "Implements mobile app changes (React Native/Expo, Flutter, native "
        "Android, native iOS) in an isolated worktree. Detects the real "
        "mobile toolchain present in the target repo rather than assuming one."
    ),
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
        "record_learning",
    ],
    "input_types": ["task_id", "subtask_id", "plan", "worktree_path", "repo_path"],
    "output_types": ["files_changed", "tokens_in", "tokens_out"],
    "side_effects": ["write_files", "execute_bash"],
    "permissions": ["read_repo", "write_worktree", "execute_bash"],
    "risk_level": "medium",
    "expected_verification": {
        "checks_run": (
            "bash-run mobile toolchain check (flutter analyze / gradlew lint "
            "/ xcodebuild / tsc, whichever matches the detected project) "
            "executed before submit"
        )
    },
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


def _detect_mobile_checks(worktree_path: str) -> list[list[str]]:
    """Real, evidence-based detection: only queue a check command for a
    mobile toolchain whose marker file actually exists in the worktree."""
    wt = Path(worktree_path)
    checks: list[list[str]] = []

    if (wt / "pubspec.yaml").exists():
        checks.append(["flutter", "analyze"])

    android_dir = wt / "android"
    if (android_dir / "build.gradle").exists() or (
        android_dir / "build.gradle.kts"
    ).exists():
        gradlew = android_dir / "gradlew"
        if gradlew.exists():
            checks.append([str(gradlew), "-p", str(android_dir), "lint"])

    ios_dir = wt / "ios"
    if ios_dir.exists():
        xcodeprojs = sorted(ios_dir.glob("*.xcodeproj"))
        if xcodeprojs:
            checks.append(["xcodebuild", "-list", "-project", str(xcodeprojs[0])])

    package_json = wt / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "react-native" in deps or "expo" in deps:
            checks.append(["npx", "tsc", "--noEmit"])

    return checks


def _run_mobile_checks(worktree_path: str) -> str | None:
    """Runs the real, detected mobile toolchain check(s). Returns error
    output, or None on success — including the honest case where no
    recognized mobile project exists yet (nothing to check against on a
    first-ever scaffold)."""
    checks = _detect_mobile_checks(worktree_path)
    if not checks:
        return None

    for cmd in checks:
        try:
            result = subprocess.run(
                cmd, cwd=worktree_path, capture_output=True, text=True, timeout=120
            )
        except FileNotFoundError:
            return (
                f"Required mobile toolchain not installed for detected "
                f"command: {' '.join(cmd)}"
            )
        except subprocess.TimeoutExpired:
            return f"Check timed out: {' '.join(cmd)}"
        if result.returncode != 0:
            return (result.stdout + result.stderr)[:3000]
    return None


# ---------------------------------------------------------------------------
# Public runner — mirrors backend_dev.run_backend_dev's external interface
# ---------------------------------------------------------------------------


def run_mobile_dev(
    task_id: int,
    subtask_id: int,
    plan: str,
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], str | None, int, int]:
    """Run mobile developer agent with a detected-toolchain static-check
    retry loop. Returns (files_changed, error, tokens_in, tokens_out)."""
    from app.fleet.failure_ladder import should_retry

    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries
    check_error: str | None = None
    total_in = 0
    total_out = 0

    for attempt in range(max_retries):
        handlers = make_coder_handlers(worktree_path, repo, extra_env=extra_env)
        handlers["record_learning"] = make_record_learning_handler("mobile_dev")

        base_msg = (
            f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
            f"Mobile Implementation Plan:\n{plan}\n\n"
            "You are a mobile developer. Implement the plan exactly as described.\n"
            "First use get_file_tree and list_files to determine which mobile "
            "toolchain this repo actually uses (pubspec.yaml = Flutter, "
            "android/+ios/ with no pubspec.yaml = native, react-native/expo "
            "in package.json = React Native) — never assume a stack the repo "
            "doesn't already have without confirming with the task/plan first.\n"
            "All file writes must be inside the worktree. "
            "When done, call submit_patch with the list of files changed."
        )
        if attempt > 0 and check_error:
            base_msg += (
                f"\n\n[SELF-CORRECTION ATTEMPT {attempt}] "
                f"Previous attempt failed static checks:\n{check_error}\n"
                "Review the errors and fix them before submitting."
            )

        try:
            final_state = run_agent_graph(
                role_name="mobile_dev",
                model=settings.model_coder,
                tools=CODER_TOOLS,
                tool_handlers=handlers,
                verification_cfg=_VERIFICATION_CFG,
                initial_message=base_msg,
                task_description=f"Mobile implementation — subtask {subtask_id}",
                repo_path=repo,
                model_haiku=settings.model_router,
                enable_planning=True,
                enable_memory=True,
                enable_reflection=True,
                enable_lesson=True,
                enable_critique=True,
                max_turns=30,
                task_id=str(task_id),
            )
        except Exception as exc:
            logger.exception(
                "Mobile dev agent failed on attempt %d for subtask %d",
                attempt + 1,
                subtask_id,
            )
            if not should_retry(attempt + 1, max_retries):
                return [], f"Mobile dev agent error: {exc}", total_in, total_out
            continue

        total_in += final_state.get("tokens_in", 0)
        total_out += final_state.get("tokens_out", 0)

        patch_result = handlers.get("_patch_result", {})
        files_changed: list[str] = patch_result.get("files_changed", [])

        if not final_state.get("submitted"):
            logger.warning("Mobile dev did not submit on attempt %d", attempt + 1)
            if not should_retry(attempt + 1, max_retries):
                return [], "Mobile dev did not submit a patch", total_in, total_out
            continue

        check_error = _run_mobile_checks(worktree_path)
        if check_error is None:
            logger.info(
                "Mobile dev done — subtask %d, attempt %d, %d files, in=%d out=%d",
                subtask_id,
                attempt + 1,
                len(files_changed),
                total_in,
                total_out,
            )
            return files_changed, None, total_in, total_out

        logger.warning(
            "Mobile dev checks failed on attempt %d: %s",
            attempt + 1,
            check_error[:200],
        )
        if not should_retry(attempt + 1, max_retries):
            return (
                [],
                f"Checks still failing after {max_retries} attempts:\n{check_error}",
                total_in,
                total_out,
            )

    return [], f"Mobile dev blocked after {max_retries} attempts", total_in, total_out


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
                capabilities=["mobile_development"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("mobile_dev")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
