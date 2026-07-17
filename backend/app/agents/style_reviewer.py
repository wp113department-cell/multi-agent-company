"""Style Reviewer Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - lint_ran is forced to state["verification"]["lint_ran"]
  - run_linter sets lint_ran to True only if it exits without [ERROR]
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import STYLE_REVIEWER_TOOLS, make_style_reviewer_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "style_reviewer",
    "description": "Enforces code style via linter, naming conventions, and import hygiene. Read-only — no file writes.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "run_linter", "list_functions", "list_classes",
        "submit_style_review",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {"lint_ran": "run_linter must execute before submit"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={"run_linter": "lint_ran"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"lint_ran": "lint_ran"},
    initial={"lint_ran": False},
)


def run_style_reviewer(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_style_reviewer_handlers(repo)

    message = (
        f"Task #{task_id} — Style / Lint Review\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Run run_linter on the target path — MANDATORY first step.\n"
        "2. Use read_file on files with violations to understand the context.\n"
        "3. Use list_functions / list_classes for naming convention review.\n"
        "4. Use find_todos to surface TODO/FIXME/HACK comments.\n"
        "5. Call submit_style_review with summary, violations list, auto_fixable flag.\n"
        "   Note: violations must come from actual linter output — never from memory."
    )

    final_state = run_agent_graph(
        role_name="style_reviewer",
        model=settings.model_coder,
        tools=STYLE_REVIEWER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=15,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=list(raw.get("violations", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("lint_ran", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
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
            capabilities=["style_review", "linting", "code_style_enforcement"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
