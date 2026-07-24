"""slo_agent — defines SLOs with concrete measurement queries from existing monitoring config."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "slo_agent",
    "description": "Defines Service Level Objectives from existing monitoring config and codebase metrics. Produces concrete PromQL queries, error budgets, and alerting thresholds — never invents SLO numbers without evidence.",
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
        "submit_slo_agent",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes SLO specification documents"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file must run to inspect monitoring config before defining SLOs"
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_slo_agent",
    "description": "Submit slo_agent result.",
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
    "description": "Write SLO specification document.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [_WRITE, _SUBMIT]

_CFG = VerificationConfig(
    set_by={"read_file": "read", "search_code": "read", "analyze_file": "read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read"},
    initial={"read": False},
)


def make_slo_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_slo_agent"] = submit_h
    base["_result"] = result
    return base


def run_slo_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_slo_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Read monitoring config, existing metrics definitions, and any existing SLO/SLA documents.\n"
        "2. State what is currently being measured and what baseline performance looks like.\n"
        "3. Define the minimum SLO set that covers user-facing contracts that actually matter.\n"
        "4. Each SLO must include: metric name, measurement window, target threshold, PromQL query.\n"
        "5. Never invent SLO numbers — derive targets from existing baseline data or explicit requirements.\n"
        "6. Write the SLO specification with write_file.\n"
        "7. Call submit_slo_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="slo_agent",
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
    )

    raw = result if result else final_state["result"]
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
                capabilities=["slo_definition"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
