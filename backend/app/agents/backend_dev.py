"""Backend Developer Agent — implements server-side changes in an isolated worktree.

Session 2 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph() inside the static-check retry loop.
- Added AGENT_CONTRACT (risk_level: medium — writes to worktree, executes bash).
- Registered in capability_registry at module level.
- External interface (run_backend_dev signature + return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
Static-check retry loop kept because mypy/ruff run OUTSIDE the LLM graph.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    CODER_TOOLS,
    make_coder_handlers,
    make_record_learning_handler,
)
from app.config import get_settings
from app.tools.agents.delegate import (
    DELEGATE_TO_AGENT_TOOL,
    make_delegate_to_agent_handler,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "backend_dev",
    "description": "Implements server-side changes in an isolated worktree — Python/FastAPI only.",
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
        # plan14 follow-on #2 (Dynamic Subtask Creation) — declared here so
        # Day 1's dynamic-tool-selection contract-drift check doesn't strip
        # this high-risk tool when both features are enabled together; the
        # tool itself is only actually wired into a given run when
        # settings.dynamic_subtask_creation_enabled_agents["backend_dev"]
        # is True (see run_backend_dev's subtask_proposal_sink parameter).
        "propose_subtask",
        # tool_enhance.md productionization pass, tool #3 (2026-08-15) —
        # real gap found while auditing delegate_to_agent: config.py's
        # delegation_allowed_matrix already listed "backend_dev":
        # ["security_review", "research_spike"] as real, intended policy,
        # but this agent never actually had the tool wired in — a real,
        # silently-unusable capability, not a security hole (the matrix +
        # base_graph.py's dispatch-authorization gate already refuse an
        # unadvertised/unauthorized call either way).
        "delegate_to_agent",
        "bhaskar_tool",
    ],
    "input_types": ["task_id", "subtask_id", "plan", "worktree_path", "repo_path"],
    "output_types": ["files_changed", "tokens_in", "tokens_out"],
    "side_effects": ["write_files", "execute_bash"],
    "permissions": ["read_repo", "write_worktree", "execute_bash"],
    "risk_level": "medium",
    "expected_verification": {"checks_run": "bash mypy/ruff executed before submit"},
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


def _run_backend_checks(worktree_path: str) -> str | None:
    """Run mypy + ruff + black --check in the backend directory. Returns
    error output or None on success.

    AUDIT_Q_BATCH16 §90 gap-closure (2026-08-11) — "Formatting" was NO: no
    black/formatter invocation anywhere in the mandatory Dev→QA→Review gate
    path, despite black already being a real project dependency
    (requirements-dev.txt) used by this exact same "python -m black
    --check ." invocation in .github/workflows/ci.yml's own format-check
    gate. Added as a third check in the SAME retry-gated static-check list
    mypy/ruff already use — a formatting failure now triggers the same
    self-correction retry loop (run_backend_dev's check_error feedback) as
    a real type or lint error, not a new/separate gate.
    """
    python = sys.executable
    checks = [
        [python, "-m", "mypy", ".", "--ignore-missing-imports", "--no-error-summary"],
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "black", "--check", "."],
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


def run_backend_dev(
    task_id: int,
    subtask_id: int,
    plan: str,
    worktree_path: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
    extra_env: dict[str, str] | None = None,
    subtask_proposal_sink: list[dict[str, Any]] | None = None,
) -> tuple[list[str], str | None, int, int]:
    """Run backend developer agent with static-check retry loop.

    Returns (files_changed, error, tokens_in, tokens_out). error is None on
    success. tokens_in/tokens_out are accumulated across every retry attempt
    (not just the last one) — MASTER_AGENT_v2.md Phase 3.2: this is real data
    the graph already computes per attempt; before this it was logged and
    then discarded at every return point instead of being surfaced to the
    caller, which is why manager.py's epic cost_actual had nothing real to
    aggregate.

    extra_env (Day 17): custom secrets merged into the bash tool's
    subprocess env.

    subtask_proposal_sink (plan14 follow-on #2, Dynamic Subtask Creation):
    None (the default) means today's exact behavior — no propose_subtask
    tool exists for this run at all. When the caller (app.agents.manager.
    _dispatch_one_subtask, itself gated by settings.
    dynamic_subtask_creation_enabled_agents) passes a list, propose_subtask
    is wired in and any proposal the agent makes is appended to that list —
    owned and read by the caller, never by this function, which only ever
    appends.
    """
    from app.fleet.failure_ladder import should_retry

    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries
    check_error: str | None = None
    total_in = 0
    total_out = 0

    for attempt in range(max_retries):
        handlers = make_coder_handlers(worktree_path, repo, extra_env=extra_env)
        handlers["record_learning"] = make_record_learning_handler("backend_dev")
        # tool_enhance.md productionization pass, tool #3 (2026-08-15) —
        # wires the real capability config.py's delegation_allowed_matrix
        # already grants this agent (see AGENT_CONTRACT's own comment
        # above for why this was previously a real, unreachable gap).
        # ancestry starts as just this agent's own name — backend_dev is
        # always the first link in a chain it initiates.
        handlers["delegate_to_agent"] = make_delegate_to_agent_handler(
            source_agent="backend_dev",
            task_id=str(task_id),
            repo_path=repo,
            ancestry=("backend_dev",),
            delegation_depth=0,
            budget_remaining_usd=settings.delegation_default_budget_usd,
        )

        tools = CODER_TOOLS + [DELEGATE_TO_AGENT_TOOL]
        if subtask_proposal_sink is not None:
            from app.tools.agents.propose_subtask import (
                PROPOSE_SUBTASK_TOOL,
                make_propose_subtask_handler,
            )

            tools = tools + [PROPOSE_SUBTASK_TOOL]
            handlers["propose_subtask"] = make_propose_subtask_handler(
                subtask_proposal_sink
            )

        base_msg = (
            f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
            f"Backend Implementation Plan:\n{plan}\n\n"
            "You are a backend developer. Implement the plan exactly as described.\n"
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
                role_name="backend_dev",
                model=settings.model_coder,
                tools=tools,
                tool_handlers=handlers,
                verification_cfg=_VERIFICATION_CFG,
                initial_message=base_msg,
                task_description=f"Backend implementation — subtask {subtask_id}",
                repo_path=repo,
                model_haiku=settings.model_router,
                enable_planning=True,
                enable_memory=True,
                enable_reflection=True,
                enable_lesson=True,
                # Gap-closure Days 11-14 (Stage 1.1, answers.md): one of the 5
                # highest output-risk agents opted into self-critique ahead of
                # a fleet-wide default flip — see coder.py's identical comment
                # for the mechanism.
                enable_critique=True,
                max_turns=30,
                task_id=str(task_id),
            )
        except Exception as exc:
            logger.exception(
                "Backend dev agent failed on attempt %d for subtask %d",
                attempt + 1,
                subtask_id,
            )
            if not should_retry(attempt + 1, max_retries):
                return [], f"Backend dev agent error: {exc}", total_in, total_out
            continue

        total_in += final_state.get("tokens_in", 0)
        total_out += final_state.get("tokens_out", 0)

        patch_result = handlers.get("_patch_result", {})
        files_changed: list[str] = patch_result.get("files_changed", [])

        if not final_state.get("submitted"):
            logger.warning("Backend dev did not submit on attempt %d", attempt + 1)
            if not should_retry(attempt + 1, max_retries):
                return [], "Backend dev did not submit a patch", total_in, total_out
            continue

        check_error = _run_backend_checks(worktree_path)
        if check_error is None:
            logger.info(
                "Backend dev done — subtask %d, attempt %d, %d files, in=%d out=%d",
                subtask_id,
                attempt + 1,
                len(files_changed),
                total_in,
                total_out,
            )
            return files_changed, None, total_in, total_out

        logger.warning(
            "Backend dev checks failed on attempt %d: %s",
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

    return [], f"Backend dev blocked after {max_retries} attempts", total_in, total_out


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
                capabilities=["backend_development", "python_coding"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("backend_dev")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
