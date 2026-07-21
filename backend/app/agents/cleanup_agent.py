"""Cleanup Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - dead_code_scanned is forced to state["verification"]["dead_code_scanned"]
  - dead_code_detect sets it; edit_file / delete_file reset it (scan must re-run after mutation)
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import CLEANUP_AGENT_TOOLS, make_cleanup_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "cleanup_agent",
    "description": "Removes dead code, organizes imports, and deletes unused files with scan-before-delete enforcement.",
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
        "dead_code_detect",
        "organize_imports",
        "delete_file",
        "edit_file",
        "bash",
        "submit_cleanup",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["edits source files", "deletes files", "reorganizes imports"],
    "permissions": ["read_repo", "write_repo"],
    "risk_level": "medium",
    "expected_verification": {
        "dead_code_scanned": "dead_code_detect must run before any deletions"
    },
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={"dead_code_detect": "dead_code_scanned"},
    reset_by=("edit_file", "delete_file"),
    reset_keys=("dead_code_scanned",),
    enforce_in_result={"dead_code_scanned": "dead_code_scanned"},
    initial={"dead_code_scanned": False},
)


def run_cleanup_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_cleanup_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Code Cleanup\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Run dead_code_detect FIRST — MANDATORY before any deletions.\n"
        "   The graph forces dead_code_scanned=False until this runs.\n"
        "2. Use find_todos / search_code to find other cleanup opportunities.\n"
        "3. Use bash (ruff --check) to find import and formatting issues.\n"
        "4. Make changes conservatively: use organize_imports for import cleanup,\n"
        "   edit_file for removing unused code, delete_file ONLY for genuinely dead files.\n"
        "   Note: each edit/delete resets dead_code_scanned — re-run dead_code_detect after.\n"
        "5. Never delete a file without confirming it has zero references in find_references.\n"
        "6. Call submit_cleanup with summary, dead_code_removed, files_deleted, imports_cleaned."
    )

    final_state = run_agent_graph(
        role_name="cleanup_agent",
        model=settings.model_coder,
        tools=CLEANUP_AGENT_TOOLS,
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
        max_turns=25,
    )

    raw = final_state["result"]
    files_deleted = list(raw.get("files_deleted", []))
    dead_code_removed = list(raw.get("dead_code_removed", []))
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[
            {
                "dead_code_removed": dead_code_removed,
                "imports_cleaned": raw.get("imports_cleaned", []),
            }
        ],
        files_touched=files_deleted + list(raw.get("imports_cleaned", [])),
        verified=bool(final_state["verification"].get("dead_code_scanned", False)),
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
                capabilities=[
                    "code_cleanup",
                    "dead_code_removal",
                    "import_organization",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
