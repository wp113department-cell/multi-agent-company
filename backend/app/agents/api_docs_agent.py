"""API Docs Agent — LangGraph StateGraph, writes only .md files.

Verification contract:
  - routes_found forced True only when find_route / find_api ran
  - Documented endpoints must come from actual tool reads, not memory
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import API_DOCS_AGENT_TOOLS, make_api_docs_agent_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "api_docs_agent",
    "description": "Documents API endpoints by reading actual route handlers and Pydantic schemas.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "find_route", "find_api", "parse_ast", "list_functions",
        "write_file", "submit_docs",
    ],
    "input_types": ["task_id", "doc_request", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes .md files"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {"routes_found": "find_route must run"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "find_route": "routes_found",
        "find_api": "api_found",
        "parse_ast": "ast_ran",
        "read_file": "files_read",
        "write_file": "docs_written",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"routes_found": "routes_found"},
    initial={"routes_found": False, "api_found": False, "ast_ran": False,
             "files_read": False, "docs_written": False},
)


def run_api_docs_agent(
    task_id: int,
    doc_request: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_api_docs_agent_handlers(repo)

    message = (
        f"Task #{task_id} — API Documentation Task\n\n{doc_request}\n\n"
        "Process:\n"
        "1. Use find_route to enumerate all @router.get/post/put/delete decorators.\n"
        "2. Use find_api to get the handler function details.\n"
        "3. Use parse_ast on each router file to extract real parameter names, types, returns.\n"
        "4. Use read_file to inspect Pydantic schemas used as request/response bodies.\n"
        "5. Draft docs per endpoint: method, path, params (from actual annotations), "
        "   request body, response shape — ONLY fields found in real handler code.\n"
        "6. Write to docs/ with write_file (only .md files).\n"
        "7. Call submit_docs with endpoints list, spec_drift, summary.\n"
        "RULE: Never document a parameter or response field you did not read from the actual "
        "handler code in this run. If a return type is unannotated, say 'unannotated'."
    )

    final_state = run_agent_graph(
        role_name="api_docs_agent",
        model=settings.model_planner,
        tools=API_DOCS_AGENT_TOOLS,
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
        summary=str(raw.get("summary", f"{len(raw.get('endpoints', []))} endpoints documented")),
        findings=list(raw.get("spec_drift", [])),
        files_touched=list(raw.get("files_written", [])),
        verified=bool(final_state["verification"].get("routes_found", False)),
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
            capabilities=["api_documentation", "endpoint_documentation"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
