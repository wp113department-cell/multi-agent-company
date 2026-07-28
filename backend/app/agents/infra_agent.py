"""infra_agent — reviews cloud infrastructure code for security risks and misconfigurations."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    INFRA_DRY_RUN_BASH_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_infra_dry_run_bash_handler,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "infra_agent",
    "description": "Reviews cloud infrastructure code (Terraform, K8s, Dockerfiles, CI/CD) for security risks, missing resource limits, hardcoded secrets, and misconfigurations.",
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
        "bash",
        "submit_infra_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [
        "writes infrastructure security reports",
        "runs dry-run/plan validation commands — never applies or deploys",
    ],
    "permissions": ["read_repo", "write_docs", "execute_infra_dry_run"],
    "risk_level": "medium",
    "expected_verification": {
        "read": "read_file must run to inspect infrastructure files"
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_infra_agent",
    "description": "Submit infra_agent result.",
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
    "description": "Write infrastructure review report.",
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
    INFRA_DRY_RUN_BASH_TOOL,
]

_CFG = VerificationConfig(
    set_by={
        "read_file": "read",
        "search_code": "read",
        "get_file_tree": "read",
        # MASTER_AGENT_v2.md Phase 2.1 (Executor tier) — "must be able to
        # apply and verify an infra change in a sandboxed/dry-run mode at
        # minimum." Tracked separately from AgentResult.verified (like
        # load_test_agent's smoke_tested): docker/helm may not be installed
        # in every environment, a finding-only run (no infra change
        # proposed) has nothing to dry-run in the first place, and
        # terraform/kubectl changes can never set this flag at all — see
        # INFRA_DRY_RUN_ALLOWED_PREFIXES's docstring in tools.py.
        "bash": "dry_run_validated",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read", "dry_run_validated": "dry_run_validated"},
    initial={"read": False, "dry_run_validated": False},
)


def make_infra_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_infra_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    base["bash"] = make_infra_dry_run_bash_handler(repo_path)
    return base


def run_infra_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_infra_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Read infrastructure files (Terraform, Dockerfiles, K8s manifests, CI/CD config).\n"
        "2. State what cloud provider, services, and security model are in use before assessing any risks.\n"
        "3. Each finding must cite: specific resource, file:line, and the concrete risk (unauthorized access, data loss, etc.).\n"
        "4. Each recommendation must specify the exact config change and how to verify it.\n"
        "5. Do not flag stylistic preferences — only security risks and misconfigurations.\n"
        "6. When you're proposing a specific config change, validate it with bash in "
        "dry-run/lint mode only (docker build, docker-compose config, helm "
        "template/lint) — never deploy. terraform and kubectl are not available "
        "here (blocked fleet-wide by policy, no dry-run exception) — for those, "
        "state what you'd run and why, without claiming it was executed. If the "
        "relevant tool isn't installed, say so rather than claiming it was validated.\n"
        "7. Write a security review report with write_file if requested.\n"
        "8. Call submit_infra_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="infra_agent",
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
                capabilities=["infrastructure_security_review"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
