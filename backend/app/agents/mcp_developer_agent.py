"""mcp_developer_agent — builds Model Context Protocol (MCP) servers and
clients FOR THE USER's own project.

AUDIT_Q_BATCH17 §71 gap-closure (2026-08-12) — "MCP Development: NO — real
but mislabeled adjacent capability. Gridiron has a real MCP *server*
(exposes its own repo-intelligence tools via stdio JSON-RPC) — but this is
Gridiron acting as an MCP server, not a capability that helps a user build/
develop their own MCP servers/clients. Separately, tool specs labeled 'MCP /
External integration' in tools.py are actually plain GitHub/webhook tool
specs, a naming mismatch, not real MCP protocol work." The tools.py labeling
was fixed separately (see that file's Day 3G section comments). This agent
is the actual missing capability: real MCP protocol scaffolding (JSON-RPC
tools/resources/prompts discovery, stdio or HTTP transport) for a project
the user is building, tested by actually running it.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _EDIT_FILE_TOOL_SPEC,
    _FETCH_URL_TOOL,
    _WEB_SEARCH_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "mcp_developer_agent",
    "description": (
        "Builds Model Context Protocol (MCP) servers and clients for the "
        "user's own project — real JSON-RPC tools/resources/prompts "
        "scaffolding over stdio or HTTP transport, verified by actually "
        "running it. Distinct from Gridiron's own MCP server (infra Gridiron "
        "runs to expose itself, not a user-facing dev capability) and from "
        "the plain GitHub/Linear/Slack integration tool specs elsewhere in "
        "this fleet, which are not MCP protocol."
    ),
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "search_symbols",
        "find_references",
        "analyze_file",
        "read_files",
        "file_exists",
        "file_info",
        "find_todos",
        "search_imports",
        "edit_file",
        "write_file",
        "bash",
        "web_search",
        "fetch_url",
        "submit_mcp_developer_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes MCP server/client code", "executes bash to test it"],
    "permissions": ["read_repo", "write_repo", "execute_bash"],
    "risk_level": "medium",
    "expected_verification": {
        "tested": "bash must run after write/edit to prove the MCP server/client actually starts"
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_mcp_developer_agent",
    "description": "Submit mcp_developer_agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}
_BASH = {
    "name": "bash",
    "description": (
        "Run a shell command to install MCP SDK dependencies, start the "
        "server/client, or run its test suite. Use this to prove the "
        "implementation actually works — never claim it works without "
        "running it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
        },
        "required": ["command"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _BASH,
    _SUBMIT,
    RECORD_LEARNING_TOOL,
    _WEB_SEARCH_TOOL,
    _FETCH_URL_TOOL,
]

_CFG = VerificationConfig(
    set_by={"bash": "tested"},
    reset_by=("edit_file", "write_file"),
    reset_keys=("tested",),
    enforce_in_result={"tested": "tested"},
    initial={"tested": False},
)


def make_mcp_developer_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_mcp_developer_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    return base


def run_mcp_developer_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_mcp_developer_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "You build MCP (Model Context Protocol) servers/clients for the "
        "USER's own project — real JSON-RPC protocol code, not a generic "
        "webhook/REST integration.\n"
        "1. Read the target project to understand its language/runtime and "
        "any existing MCP-adjacent code before writing anything.\n"
        "2. The MCP spec evolves — if you're not certain of the current "
        "transport/handshake/tool-schema requirements, use web_search and "
        "fetch_url to confirm against current documentation rather than "
        "relying on training data.\n"
        "3. Implement using edit_file/write_file: server or client exposing "
        "real tools/resources/prompts per the protocol, over stdio or HTTP "
        "as appropriate for the target use case.\n"
        "4. Use bash to actually install dependencies and run/start what you "
        "built (or its test suite) — the graph forces tested=False until "
        "bash runs after your most recent write/edit. Never claim it works "
        "without running it.\n"
        "5. Call submit_mcp_developer_agent with summary, findings, "
        "files_written, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="mcp_developer_agent",
        model=settings.model_coder,
        tools=_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_CFG,
        initial_message=msg,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=25,
    )

    raw = final_state["result"] if final_state["result"] else result
    return AgentResult(
        summary=str(raw.get("summary", description[:100])),
        findings=list(raw.get("findings", [])),
        files_touched=list(raw.get("files_written", [])),
        verified=bool(final_state["verification"].get("tested")),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


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
                capabilities=["mcp_protocol_development"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
