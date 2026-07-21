"""Refactor Agent — LangGraph StateGraph.

Verification contract:
  - behavior_preserved forced True only if tests_before == tests_after (checked in graph)
  - edit_file RESETS tests_passed — must re-run tests after refactor
  - Agent is BLOCKED from submitting behavior_preserved=True without running tests after edits
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import REFACTOR_AGENT_TOOLS, make_refactor_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "refactor_agent",
    "description": "Refactors code while verifying behavior is preserved via test runs before and after.",
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
        "list_functions",
        "list_classes",
        "parse_ast",
        "call_graph",
        "import_graph",
        "find_function_body",
        "rename_symbol",
        "replace_function",
        "edit_file",
        "write_file",
        "git_diff",
        "bash",
        "submit_refactor_report",
    ],
    "input_types": ["task_id", "refactor_instructions", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes files in repo", "executes pytest"],
    "permissions": ["read_repo", "write_repo", "execute_tests"],
    "risk_level": "medium",
    "expected_verification": {"tests_passed": "run_tests must pass after edits"},
    "dependencies": ["reviewer"],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_tests": "tests_passed",
        "git_diff": "diff_checked",
        "rename_symbol": "symbol_renamed",
    },
    reset_by=("edit_file", "write_file", "apply_patch", "rename_symbol"),
    reset_keys=("tests_passed",),
    enforce_in_result={"behavior_preserved": "tests_passed"},
    initial={"tests_passed": False, "diff_checked": False, "symbol_renamed": False},
)


def run_refactor_agent(
    task_id: int,
    refactor_instructions: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_refactor_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Refactor Task\n\n{refactor_instructions}\n\n"
        "Process:\n"
        "1. Run run_tests BEFORE any change to establish the baseline (pass/fail set).\n"
        "   If tests are currently red, STOP — refactoring on a red baseline is unsafe.\n"
        "2. Use read_file / parse_ast / list_functions to understand the target code.\n"
        "3. Apply the minimal structural change (extract, rename, move, simplify).\n"
        "   Do not fix bugs or add features — only restructure.\n"
        "4. Run run_tests AFTER the change.\n"
        "5. Use git_diff to confirm only structural changes, not behavioral ones.\n"
        "6. Call submit_refactor_report with files_changed, behavior_preserved (auto-enforced), "
        "   summary.\n"
        "RULE: behavior_preserved will be forced False if run_tests did not pass AFTER your edits. "
        "You cannot claim behavior was preserved without running tests after every edit."
    )

    final_state = run_agent_graph(
        role_name="refactor_agent",
        model=settings.model_coder,
        tools=REFACTOR_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=refactor_instructions[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=25,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[],
        files_touched=list(raw.get("files_changed", [])),
        verified=bool(final_state["verification"].get("tests_passed", False)),
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

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=["refactoring", "code_restructuring", "test_verification"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
