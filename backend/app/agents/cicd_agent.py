"""CI/CD Agent — LangGraph StateGraph.

Always requires human approval — pipeline changes affect every future merge.

Verification contract:
  - lint_passed forced True only when bash lint command succeeds
  - write_file resets lint_passed
  - requires_human_approval ALWAYS True (cannot be overridden)
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import CICD_AGENT_TOOLS, make_cicd_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "cicd_agent",
    "description": "Manages CI/CD pipeline configuration; always requires human approval.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "bash", "edit_file", "write_file", "submit_cicd_report",
    ],
    "input_types": ["task_id", "task_description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes .github/workflows files"],
    "permissions": ["read_repo", "write_repo", "bash_allowlisted"],
    "risk_level": "high",
    "expected_verification": {"lint_ran": "yamllint/actionlint via bash must run"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "bash": "lint_ran",     # bash running actionlint/yamllint = lint
        "read_file": "files_read",
    },
    reset_by=("write_file", "edit_file"),
    reset_keys=("lint_ran",),
    enforce_in_result={"lint_passed": "lint_ran"},
    initial={"lint_ran": False, "files_read": False},
)


def run_cicd_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_cicd_agent_handlers(repo)

    message = (
        f"Task #{task_id} — CI/CD Task\n\n{task_description}\n\n"
        "Process:\n"
        "1. Use read_file on existing .github/workflows/ files.\n"
        "2. Use search_code to find how tests/build are actually invoked (Makefile, package.json).\n"
        "   Use those REAL commands in the workflow — never invent them.\n"
        "3. Never invent an action version (e.g. actions/checkout@v4) — copy from existing files "
        "   or state 'needs human to verify version'.\n"
        "4. Draft the minimal workflow change.\n"
        "5. Lint the YAML with bash (yamllint or actionlint) if available.\n"
        "6. Call submit_cicd_report with files_changed, lint_passed, summary.\n"
        "IMPORTANT: This agent ALWAYS requires human approval before changes are applied — "
        "this is non-negotiable regardless of whether lint passed."
    )

    final_state = run_agent_graph(
        role_name="cicd_agent",
        model=settings.model_coder,
        tools=CICD_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=task_description,
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        human_approval_required=True,
        max_turns=15,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=list(raw.get("warnings", [])),
        files_touched=list(raw.get("files_changed", [])),
        verified=bool(final_state["verification"].get("lint_ran", False)),
        requires_human_approval=True,  # always, non-negotiable
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="needs_approval" if final_state["submitted"] else "blocked",
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
            capabilities=["cicd_management", "pipeline_configuration", "workflow_editing"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
