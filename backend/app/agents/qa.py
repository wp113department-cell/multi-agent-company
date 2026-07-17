"""QA Agent — runs tests and checks in a worktree. No write access.

Session 3 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Updated AGENT_CONTRACT to standard format (input_types/output_types lists instead of dicts).
  Previous format was reference implementation #3 of 3 for the old pattern.
- Registered in capability_registry at module level (was previously missing _register()).
- External interface (run_qa signature + QAResult return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import QA_TOOLS, make_qa_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration (standard format)
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "qa",
    "description": "Runs pytest, mypy, and ruff in a worktree. Read + bash (test commands only). No writes.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "bash", "submit_qa_result",
    ],
    "input_types": ["task_id", "subtask_id", "files_changed", "worktree_path", "repo_path"],
    "output_types": ["QAResult"],
    "side_effects": ["execute_bash"],
    "permissions": ["read_repo", "execute_tests"],
    "risk_level": "low",
    "expected_verification": {"tests_run": "bash pytest executed before submit"},
    "dependencies": ["backend_dev", "frontend_dev", "coder"],
}

# ---------------------------------------------------------------------------
# Verification contract — tracks bash usage; no file-write resets needed
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"bash": "tests_run"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={"tests_run": False},
)

# ---------------------------------------------------------------------------
# Result dataclass — unchanged from original
# ---------------------------------------------------------------------------

@dataclass
class QAResult:
    status: str  # "passed" | "failed"
    tests_run: int
    tests_passed: int
    tests_failed: int
    typecheck_clean: bool
    lint_clean: bool
    errors: list[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------

def run_qa(
    task_id: int,
    subtask_id: int,
    files_changed: list[str],
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
) -> QAResult:
    """Run QA agent against the worktree. Returns QAResult (never raises — errors become failed status)."""
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    handlers = make_qa_handlers(worktree_path, repo)

    initial_message = (
        f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
        f"Files changed by developer: {', '.join(files_changed) or '(none listed)'}\n\n"
        "Run the test suite and all checks:\n"
        "1. Run pytest (or npm test for frontend changes)\n"
        "2. Run mypy typecheck\n"
        "3. Run ruff lint\n"
        "Capture all output. Then call submit_qa_result with the structured results."
    )

    try:
        final_state = run_agent_graph(
            role_name="qa",
            model=settings.model_coder,
            tools=QA_TOOLS,
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            task_description=f"QA testing — subtask {subtask_id}",
            repo_path=repo,
            model_haiku=settings.model_router,
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            enable_lesson=True,
            max_turns=20,
        )
        logger.info(
            "QA done — subtask %d, in=%d out=%d submitted=%s",
            subtask_id,
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("QA agent failed for subtask %d", subtask_id)
        return QAResult(
            status="failed",
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            typecheck_clean=False,
            lint_clean=False,
            errors=[f"QA agent error: {exc}"],
            summary=f"QA agent error: {exc}",
        )

    raw = handlers.get("_qa_result", {})
    logger.info(
        "QA result — subtask %d, status=%s",
        subtask_id, raw.get("status", "unknown"),
    )

    return QAResult(
        status=str(raw.get("status", "failed")),
        tests_run=int(raw.get("tests_run", 0)),
        tests_passed=int(raw.get("tests_passed", 0)),
        tests_failed=int(raw.get("tests_failed", 0)),
        typecheck_clean=bool(raw.get("typecheck_clean", False)),
        lint_clean=bool(raw.get("lint_clean", False)),
        errors=list(raw.get("errors", [])),
        summary=str(raw.get("summary", "")),
    )


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------

def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            # Include legacy tags from capability_registry.py built-in entry so existing
            # tests that query "qa_verification" / "test_execution" still resolve.
            capabilities=["testing", "qa_validation", "lint_check",
                           "test_execution", "typecheck", "lint", "qa_verification"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("qa")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
