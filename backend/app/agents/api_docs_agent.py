"""API Docs Agent — LangGraph StateGraph, writes only .md files.

Verification contract:
  - routes_found forced True only when find_route / find_api ran
  - Documented endpoints must come from actual tool reads, not memory
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import API_DOCS_AGENT_TOOLS, make_api_docs_agent_handlers
from app.config import get_settings

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
