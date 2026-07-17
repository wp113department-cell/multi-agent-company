"""Security Architect Agent — threat modelling and OWASP review. Read-only; no code changes.

Verification contract:
  - codebase_read: set True when read_file or search_code used to inspect actual code
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "security_architect",
    "description": "Performs STRIDE threat modelling and OWASP Top 10 review. Read-only analysis producing a threat model with severities and mitigations.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "search_imports", "git_status", "git_show",
        "submit_threat_model",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {"codebase_read": "must inspect actual code before performing threat modelling"},
    "dependencies": [],
}

_SUBMIT_THREAT_MODEL_TOOL: dict[str, Any] = {
    "name": "submit_threat_model",
    "description": "Submit the threat model and security findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Executive summary of security posture"},
            "threats": {
                "type": "array",
                "description": "Identified threats",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "STRIDE category or OWASP Top 10 ref"},
                        "description": {"type": "string"},
                        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                        "affected_component": {"type": "string"},
                        "mitigation": {"type": "string"},
                    },
                    "required": ["category", "description", "severity", "mitigation"],
                },
            },
            "owasp_findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "OWASP Top 10 items observed",
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "overall_risk": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        },
        "required": ["summary", "threats", "overall_risk"],
    },
}

_SECURITY_TOOLS = READ_ONLY_TOOLS + [_SUBMIT_THREAT_MODEL_TOOL]

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "codebase_read",
        "search_code": "codebase_read",
        "list_directory": "codebase_read",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"codebase_read": "codebase_read"},
    initial={"codebase_read": False},
)


def make_security_architect_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_threat_model_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        n = len(inp.get("threats", []))
        risk = inp.get("overall_risk", "?")
        return f"Threat model submitted: {n} threats, overall risk = {risk}."

    base["submit_threat_model"] = submit_threat_model_h
    base["_security_result"] = submitted
    return base


def run_security_architect(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_security_architect_handlers(repo)
    submitted = handlers["_security_result"]

    message = (
        f"Task #{task_id} — Security Architecture Review\n\n"
        f"{description}\n\n"
        "IMPORTANT: This is a READ-ONLY review. Do not write or modify any files.\n\n"
        "Process:\n"
        "1. Use read_file and search_code to inspect the codebase — MANDATORY.\n"
        "   Focus on: authentication, authorization, input validation, secrets handling, API endpoints, DB queries.\n"
        "2. Apply STRIDE threat modelling:\n"
        "   - Spoofing: identity/auth issues\n"
        "   - Tampering: data integrity issues\n"
        "   - Repudiation: audit trail gaps\n"
        "   - Information Disclosure: data exposure\n"
        "   - Denial of Service: rate limiting, resource exhaustion\n"
        "   - Elevation of Privilege: RBAC flaws\n"
        "3. Map findings to OWASP Top 10 where applicable.\n"
        "4. Rate each threat: critical/high/medium/low/info.\n"
        "5. Provide concrete mitigations for each threat.\n"
        "6. Call submit_threat_model with all findings."
    )

    final_state = run_agent_graph(
        role_name="security_architect",
        model=settings.model_coder,
        tools=_SECURITY_TOOLS,
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
        max_turns=20,
    )

    raw = submitted if submitted else final_state["result"]
    threats = raw.get("threats", [])
    critical = sum(1 for t in threats if t.get("severity") in ("critical", "high"))
    return AgentResult(
        summary=f"Security review: {len(threats)} threats ({critical} high/critical), overall risk = {raw.get('overall_risk', '?')}. {raw.get('summary', '')}",
        findings=[{"severity": t.get("severity", "?"), "category": t.get("category", "?"), "description": t.get("description", ""), "mitigation": t.get("mitigation", "")} for t in threats],
        files_touched=[],
        verified=bool(final_state["verification"].get("codebase_read", False)),
        requires_human_approval=critical > 0,
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
            capabilities=["threat_modelling", "owasp_review", "security_architecture_analysis"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
