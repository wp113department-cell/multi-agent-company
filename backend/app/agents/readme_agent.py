"""README Agent — LangGraph StateGraph, writes only .md files.

Verification contract:
  - files_read forced True only when read_file / get_file_tree actually ran
  - No source code edits — writes only to .md / docs files
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import README_AGENT_TOOLS, make_readme_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "readme_agent",
    "description": "Writes README and documentation files from real codebase inspection.",
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
        "parse_ast",
        "list_functions",
        "list_classes",
        "write_file",
        "submit_docs",
    ],
    "input_types": ["task_id", "doc_request", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes .md files"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {"files_read": "read_file/get_file_tree must run"},
    "dependencies": [],
}

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
    initial={
        "files_read": False,
        "tree_read": False,
        "ast_ran": False,
        "docs_written": False,
    },
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
        task_description=doc_request[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
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
                capabilities=["documentation_writing", "readme_generation"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
