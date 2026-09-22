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

from app.agents.base_graph import (
    TEST_COMMAND_PATTERN,
    VerificationConfig,
    run_agent_graph,
)
from app.agents.tools import QA_TOOLS, make_qa_handlers, make_record_learning_handler
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration (standard format)
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "qa",
    "description": "Runs pytest, mypy, and ruff in a worktree. Read + bash (test commands only). No writes.",
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
        "bash",
        "submit_qa_result",
        "record_learning",
        "bhaskar_tool",
    ],
    "input_types": [
        "task_id",
        "subtask_id",
        "files_changed",
        "worktree_path",
        "repo_path",
    ],
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
    enforce_in_result={"tests_run": "tests_run"},
    initial={"tests_run": False},
    # tests_run is only true after a command that looks like a test runner ran
    command_patterns={"tests_run": TEST_COMMAND_PATTERN},
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
    # MASTER_AGENT_v2.md Phase 3.2 — real token usage, previously computed
    # (see the "in=%d out=%d" log line below) and then discarded instead of
    # being surfaced to the caller.
    tokens_in: int = 0
    tokens_out: int = 0
    # AUDIT_Q_BATCH13 §43 gap-closure (2026-08-11) — the shared planner
    # (base_graph.py::_gather_facts_and_plan) already computes a real
    # confidence score for this run and puts it in final_state["confidence"];
    # it was being discarded here instead of surfaced on the result, the
    # exact "computed but not propagated" pattern flagged by the audit.
    # 0.0 means no agent run actually completed (e.g. slot-timeout fallback).
    confidence: float = 0.0
    # T2-B3 (2026-09-22, GRIDIRON_PARTIAL #130 "Confidence Evaluation feeds
    # control flow") — base_graph.py's _run_quality_gate already computes
    # this (raw_result["_requires_human_approval"]) and, when
    # quality_gate_min_confidence > 0, already registers a real pending-
    # approval row (approval_gate.py) the moment the planner's confidence
    # falls below that floor — but QAResult had no field to carry the flag
    # out to manager.py's dispatch loop at all, so a low-confidence QA pass
    # sailed straight through to the reviewer/merge stage with zero
    # visibility. sql_agent.py is the only other agent that already reads
    # this flag; qa.py is a natural second real consumer given its whole
    # job is verifying correctness.
    requires_human_approval: bool = False
    # T2-B3 (2026-09-22, GRIDIRON_PARTIAL #126/#146 "Step-by-Step Guidance
    # (dedicated renderer)") — the SAME "QA Process (follow in order)" steps
    # roles/qa.md already tells the model to follow, structured (see
    # app/agents/guidance.py). [] means the role file had no such section or
    # the graph run failed before this could be computed — not a claim that
    # QA followed no real process.
    guidance_steps: list[str] = field(default_factory=list)


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
    """Run QA agent against the worktree. Returns QAResult (never raises — errors become failed status).

    AUDIT_Q_BATCH04 §6 gap-closure (2026-08-10) — outer retry+feedback loop,
    reusing app.fleet.failure_ladder.should_retry exactly as backend_dev.py/
    frontend_dev.py already do for their static-check retries. QA has no
    static check of its own to retry (pytest/mypy/ruff run INSIDE the graph
    via the bash tool, not after it), so the retry trigger here is either an
    exception or the agent never reaching submit_qa_result — previously
    both cases gave up after a single attempt, unlike coder/backend_dev/
    frontend_dev.
    """
    from app.fleet.failure_ladder import should_retry

    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    max_retries = settings.max_retries
    total_in = 0
    total_out = 0
    last_error = ""

    for attempt in range(max_retries):
        handlers = make_qa_handlers(worktree_path, repo)
        handlers["record_learning"] = make_record_learning_handler("qa")

        initial_message = (
            f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
            f"Files changed by developer: {', '.join(files_changed) or '(none listed)'}\n\n"
            "Run the test suite and all checks:\n"
            "1. Run pytest (or npm test for frontend changes)\n"
            "2. Run mypy typecheck\n"
            "3. Run ruff lint\n"
            "Capture all output. Then call submit_qa_result with the structured results."
        )
        if attempt > 0 and last_error:
            initial_message += (
                f"\n\n[RETRY {attempt}] Previous attempt failed: {last_error}\n"
                "Make sure to run the checks and call submit_qa_result before "
                "running out of turns."
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
                # Gap-closure Days 11-14 (Stage 1.1, answers.md): one of the 5
                # highest output-risk agents opted into self-critique ahead of
                # a fleet-wide default flip — see coder.py's identical
                # comment for the mechanism.
                enable_critique=True,
                # AUDIT_Q_BATCH04 §6 gap-closure (2026-08-10) — same opt-in as
                # coder.py: qa.md has a real Quality Gates section.
                # T2-B1 (2026-09-22) — enable_replanning omitted: run_agent_graph() resolves
                # the real fleet default itself (True unless explicitly opted out for "qa").
                # T2-B3 (2026-09-22, GRIDIRON_PARTIAL #130) — second real
                # pilot agent (after spike_agent) opted into a nonzero
                # confidence floor: a low-confidence QA verdict is exactly
                # the case that should get a human's eyes before the
                # reviewer/merge stage proceeds on it. This alone is what
                # makes _run_quality_gate's existing request_human_input()
                # call fire (real pending_approvals row) — no new approval
                # mechanism needed, just opting in.
                quality_gate_min_confidence=settings.quality_gate_min_confidence_by_agent.get(
                    "qa", 0.0
                ),
                max_turns=20,
                task_id=str(task_id),
            )
        except Exception as exc:
            logger.exception(
                "QA agent failed for subtask %d (attempt %d)", subtask_id, attempt + 1
            )
            last_error = f"QA agent error: {exc}"
            if not should_retry(attempt + 1, max_retries):
                return QAResult(
                    status="failed",
                    tests_run=0,
                    tests_passed=0,
                    tests_failed=0,
                    typecheck_clean=False,
                    lint_clean=False,
                    tokens_in=total_in,
                    tokens_out=total_out,
                    errors=[last_error],
                    summary=last_error,
                )
            continue

        total_in += final_state.get("tokens_in", 0)
        total_out += final_state.get("tokens_out", 0)
        logger.info(
            "QA done — subtask %d, in=%d out=%d submitted=%s",
            subtask_id,
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )

        if not final_state.get("submitted"):
            last_error = "QA agent did not call submit_qa_result within the turn limit"
            if not should_retry(attempt + 1, max_retries):
                raw = handlers.get("_qa_result", {})
                return QAResult(
                    status=str(raw.get("status", "failed")),
                    tests_run=int(raw.get("tests_run", 0)),
                    tests_passed=int(raw.get("tests_passed", 0)),
                    tests_failed=int(raw.get("tests_failed", 0)),
                    typecheck_clean=bool(raw.get("typecheck_clean", False)),
                    lint_clean=bool(raw.get("lint_clean", False)),
                    tokens_in=total_in,
                    tokens_out=total_out,
                    errors=list(raw.get("errors", [])) or [last_error],
                    summary=str(raw.get("summary", "")) or last_error,
                    confidence=float(final_state.get("confidence", 0.8)),
                )
            continue

        # The graph tracks whether a test-runner command actually ran
        # (enforce_in_result overwrites the result the GRAPH keeps) — but this
        # function reads the handler's own copy of what the model submitted, so the
        # enforcement never reached the QAResult: a QA agent that ran nothing could
        # submit "passed, 42 tests" and the pipeline believed it.
        if not (final_state.get("verification") or {}).get("tests_run", False):
            last_error = (
                "QA submitted results without running any test command — "
                "the reported results were discarded"
            )
            logger.warning("QA subtask %d: %s", subtask_id, last_error)
            if not should_retry(attempt + 1, max_retries):
                return QAResult(
                    status="failed",
                    tests_run=0,
                    tests_passed=0,
                    tests_failed=0,
                    typecheck_clean=False,
                    lint_clean=False,
                    tokens_in=total_in,
                    tokens_out=total_out,
                    errors=[last_error],
                    summary=last_error,
                    confidence=float(final_state.get("confidence", 0.0)),
                )
            continue

        raw = handlers.get("_qa_result", {})
        logger.info(
            "QA result — subtask %d, status=%s",
            subtask_id,
            raw.get("status", "unknown"),
        )

        return QAResult(
            status=str(raw.get("status", "failed")),
            tests_run=int(raw.get("tests_run", 0)),
            tests_passed=int(raw.get("tests_passed", 0)),
            tests_failed=int(raw.get("tests_failed", 0)),
            typecheck_clean=bool(raw.get("typecheck_clean", False)),
            lint_clean=bool(raw.get("lint_clean", False)),
            tokens_in=total_in,
            tokens_out=total_out,
            errors=list(raw.get("errors", [])),
            summary=str(raw.get("summary", "")),
            confidence=float(final_state.get("confidence", 0.8)),
            # T2-B3 (#130) — the GRAPH's own result copy (final_state
            # ["result"], enforced by _run_quality_gate), not handlers'
            # "_qa_result" sink above (the model's raw, pre-enforcement
            # submission) — _requires_human_approval is only ever set on the
            # former.
            requires_human_approval=bool(
                final_state.get("result", {}).get("_requires_human_approval", False)
            ),
            # T2-B3 (#126/#146) — the SAME "QA Process (follow in order)"
            # steps roles/qa.md already tells the model to follow, structured.
            guidance_steps=list(
                final_state.get("result", {}).get("_guidance_steps", [])
            ),
        )

    return QAResult(
        status="failed",
        tests_run=0,
        tests_passed=0,
        tests_failed=0,
        typecheck_clean=False,
        lint_clean=False,
        tokens_in=total_in,
        tokens_out=total_out,
        errors=[last_error or f"QA blocked after {max_retries} attempts"],
        summary=last_error or f"QA blocked after {max_retries} attempts",
    )


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
                # Include legacy tags from capability_registry.py built-in entry so existing
                # tests that query "qa_verification" / "test_execution" still resolve.
                capabilities=[
                    "testing",
                    "qa_validation",
                    "lint_check",
                    "test_execution",
                    "typecheck",
                    "lint",
                    "qa_verification",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("qa")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
