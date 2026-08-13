"""spike_agent — conducts a time-boxed research spike and returns a concrete recommendation."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _FETCH_URL_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    _WEB_SEARCH_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "spike_agent",
    "description": "Conducts a time-boxed research spike: investigates a specific technical question, reads relevant code and packages, searches the web and fetches external documentation when local context isn't enough, and returns a concrete recommendation — not a survey of all options.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "search_symbols",
        "find_references",
        "list_functions",
        "parse_ast",
        "analyze_file",
        "read_files",
        "file_exists",
        "file_info",
        "find_todos",
        "search_imports",
        "write_file",
        "web_search",
        "fetch_url",
        "submit_spike_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes spike research reports"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file must run to verify findings against actual installed versions"
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_spike_agent",
    "description": "Submit spike_agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}
_WRITE = {
    "name": "write_file",
    "description": "Write spike research report.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [
    _WRITE,
    _SUBMIT,
    RECORD_LEARNING_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    _WEB_SEARCH_TOOL,
    _FETCH_URL_TOOL,
]

_CFG = VerificationConfig(
    set_by={"read_file": "read", "search_code": "read", "analyze_file": "read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read"},
    initial={"read": False},
)


def make_spike_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_spike_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    # AUDIT_Q_BATCH09 §79/80 gap-closure — spike_agent is the agent closest to
    # a "research an unfamiliar technology" role but previously had no way to
    # reach anything outside the local repo. Both web_search and fetch_url
    # are now real handlers in make_chat_handlers() itself (see tools.py),
    # so no extra wiring is needed here beyond declaring them in allowed_tools.
    return base


def run_spike_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_spike_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "RESEARCH SPIKE — state the specific question this spike must answer before starting:\n"
        "1. Identify the precise question: what decision does this spike enable?\n"
        "2. Read relevant code files, requirements, and installed package versions.\n"
        "   If the question involves a library, API, or technology you cannot verify from "
        "the repo alone, use web_search and fetch_url to check current, external "
        "documentation rather than relying on training data.\n"
        "3. Every finding must trace to something read in this session — never from training data alone.\n"
        "4. End with ONE concrete recommendation, not a survey of all options.\n"
        "5. State your recommendation first, then the supporting evidence.\n"
        "6. Write the spike report with write_file.\n"
        "7. Call submit_spike_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="spike_agent",
        model=settings.model_planner,
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
        max_turns=20,
        # plan14 Day 1 Task 2 pilot agent — config-driven, staged rollout of
        # the confidence-gated control flow (see config.py's
        # quality_gate_min_confidence_by_agent docstring). Absent from the
        # dict falls back to 0.0, today's unchanged inert default.
        quality_gate_min_confidence=settings.quality_gate_min_confidence_by_agent.get(
            AGENT_CONTRACT["name"], 0.0
        ),
    )

    # MASTER_AGENT_v2.md Phase 3.4 gap-closure (2026-07-28) - final_state["result"]
    # (graph-enforced, enforce_in_result-overridden) must win over the handler-
    # captured `result` dict, which is the model's raw, un-overridden submit_*
    # claim; the old priority let a false verification claim leak into
    # AgentResult.raw even though .verified itself was already correct.
    raw = final_state["result"] if final_state["result"] else result
    return AgentResult(
        summary=str(raw.get("summary", description[:100])),
        findings=list(raw.get("findings", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("read")),
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
                capabilities=["research_spike"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
