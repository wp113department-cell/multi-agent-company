"""README Agent — LangGraph StateGraph, writes only .md files.

Verification contract:
  - files_read forced True only when read_file / get_file_tree actually ran
  - No source code edits — writes only to .md / docs files
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import README_AGENT_TOOLS, make_readme_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "files_read",
        "get_file_tree": "tree_read",
        "parse_ast": "ast_ran",
        "write_file": "docs_written",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"files_read": "files_read"},
    initial={"files_read": False, "tree_read": False, "ast_ran": False, "docs_written": False},
)


def run_readme_agent(
    task_id: int,
    doc_request: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_readme_agent_handlers(repo)

    message = (
        f"Task #{task_id} — README / Documentation Task\n\n{doc_request}\n\n"
        "Process:\n"
        "1. Use get_file_tree to map the repo structure.\n"
        "2. Use read_file on the actual manifest (pyproject.toml, package.json, requirements.txt) "
        "   to extract real install / run / test commands.\n"
        "3. Use parse_ast on key modules to extract real function signatures for usage examples.\n"
        "4. Draft each README section — every command must match something found in step 2-3.\n"
        "5. Write to README.md or docs/ with write_file (only .md files allowed).\n"
        "6. Call submit_docs with content_markdown, verified_commands, sections.\n"
        "RULE: Never write an install or run command you did not find in an actual manifest file. "
        "If a command was not read from a real file, say 'unverified — check with project maintainer'."
    )

    final_state = run_agent_graph(
        role_name="readme_agent",
        model=settings.model_planner,
        tools=README_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", f"Docs written: {raw.get('sections', [])}")),
        findings=[],
        files_touched=list(raw.get("files_written", [])),
        verified=bool(final_state["verification"].get("files_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
