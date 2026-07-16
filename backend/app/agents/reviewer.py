"""Code Review Agent — reads diffs and produces structured findings. Read-only.

Session 3 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: low — read-only, no side effects).
- Registered in capability_registry at module level.
- External interface (run_reviewer signature + ReviewResult return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import REVIEWER_TOOLS, make_reviewer_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "reviewer",
    "description": "Reads diffs and codebase context to produce structured code-review findings.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "submit_review",
    ],
    "input_types": ["task_id", "subtask_id", "diff", "plan", "repo_path"],
    "output_types": ["ReviewResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": ["coder", "backend_dev", "frontend_dev"],
}

# ---------------------------------------------------------------------------
# Verification contract — read-only agent, no mutation to track
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={},
)

# ---------------------------------------------------------------------------
# Result dataclasses — unchanged from original
# ---------------------------------------------------------------------------

@dataclass
class ReviewFinding:
    severity: str  # "blocking" | "non-blocking" | "suggestion"
    file: str
    line: int | None
    finding: str
    recommendation: str


@dataclass
class ReviewResult:
    verdict: str  # "approved" | "changes_required"
    findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""

    @property
    def blocking_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "blocking")

    @property
    def has_blocking(self) -> bool:
        return self.blocking_count > 0


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------

def run_reviewer(
    task_id: int,
    subtask_id: int,
    diff: str,
    plan: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
) -> ReviewResult:
    """Run code review agent. Returns ReviewResult (never raises — errors become blocking findings)."""
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    handlers = make_reviewer_handlers(repo)

    diff_preview = diff[:4000] if diff else "(no diff available)"

    initial_message = (
        f"Task ID: {task_id}, Subtask ID: {subtask_id}\n\n"
        f"Approved Implementation Plan:\n{plan}\n\n"
        f"Code Diff (first 4000 chars):\n{diff_preview}\n\n"
        "Review this implementation. Read any files you need to understand the context.\n"
        "Produce structured findings categorized as blocking, non-blocking, or suggestion.\n"
        "Call submit_review when done with all findings."
    )

    try:
        final_state = run_agent_graph(
            role_name="reviewer",
            model=settings.model_coder,
            tools=REVIEWER_TOOLS,
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            max_turns=15,
        )
        logger.info(
            "Review done — subtask %d, in=%d out=%d submitted=%s",
            subtask_id,
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("Reviewer agent failed for subtask %d", subtask_id)
        return ReviewResult(
            verdict="changes_required",
            findings=[ReviewFinding(
                severity="blocking",
                file="",
                line=None,
                finding=f"Reviewer agent error: {exc}",
                recommendation="Investigate agent failure",
            )],
            summary=f"Reviewer agent error: {exc}",
        )

    raw = handlers.get("_review_result", {})
    raw_findings: list[dict[str, Any]] = raw.get("findings", [])
    findings = [
        ReviewFinding(
            severity=str(f.get("severity", "suggestion")),
            file=str(f.get("file", "")),
            line=f.get("line"),
            finding=str(f.get("finding", "")),
            recommendation=str(f.get("recommendation", "")),
        )
        for f in raw_findings
    ]

    return ReviewResult(
        verdict=str(raw.get("verdict", "changes_required")),
        findings=findings,
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
            capabilities=["code_review", "diff_analysis", "security_review"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("reviewer")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
