"""Cleanup Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - dead_code_scanned is forced to state["verification"]["dead_code_scanned"]
  - dead_code_detect sets it; edit_file / delete_file reset it (scan must re-run after mutation)
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import CLEANUP_AGENT_TOOLS, make_cleanup_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={"dead_code_detect": "dead_code_scanned"},
    reset_by=("edit_file", "delete_file"),
    reset_keys=("dead_code_scanned",),
    enforce_in_result={},
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
        max_turns=25,
    )

    raw = final_state["result"]
    files_deleted = list(raw.get("files_deleted", []))
    dead_code_removed = list(raw.get("dead_code_removed", []))
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[{"dead_code_removed": dead_code_removed, "imports_cleaned": raw.get("imports_cleaned", [])}],
        files_touched=files_deleted + list(raw.get("imports_cleaned", [])),
        verified=bool(final_state["verification"].get("dead_code_scanned", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
