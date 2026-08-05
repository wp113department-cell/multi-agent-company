"""dependency_security_agent — scans dependencies for known CVEs and version vulnerabilities."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    DEPENDENCY_AUDIT_BASH_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_dependency_audit_bash_handler,
    make_record_learning_handler,
    make_submit_enhancement_request_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "dependency_security_agent",
    "description": "Scans project dependencies for known CVEs and reports the specific vulnerability, affected version, and minimum safe upgrade version.",
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
        "submit_dependency_security_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes vulnerability reports"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file must run to inspect dependency files",
        "audited": "bash (pip-audit/npm audit) must actually run before a CVE claim — gap-closure Day 7, answers.md Q92",
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_dependency_security_agent",
    "description": "Submit dependency_security_agent result.",
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
    "description": "Write vulnerability report.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [
    _WRITE,
    DEPENDENCY_AUDIT_BASH_TOOL,
    _SUBMIT,
    RECORD_LEARNING_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
]

_CFG = VerificationConfig(
    set_by={
        "read_file": "read",
        "search_code": "read",
        "analyze_file": "read",
        "bash": "audited",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read", "audited": "audited"},
    initial={"read": False, "audited": False},
    # Gap-closure Day 15 (Stage 1.2, answers.md): expected_verification's
    # "read" requirement is now a real blocking check, not just tracked
    # metadata — bash (the audit tool) is refused with a real
    # [POLICY DENIED] result, the sandboxed subprocess never runs, until at
    # least one real read (read_file/search_code/analyze_file) has
    # happened first. Matches this role's own prompt
    # (roles/dependency_security_agent.md Process step 1: "Read relevant
    # files... to identify manifests in scope" before step 2's audit run).
    blocking_until={"bash": "read"},
)


def make_dependency_security_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_dependency_security_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    base["bash"] = make_dependency_audit_bash_handler(repo_path)
    return base


def run_dependency_security_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_dependency_security_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Read requirements.txt, package.json, and any lockfiles to identify all dependencies.\n"
        "2. For each dependency, check the pinned version against known CVE databases.\n"
        "3. Every finding must cite: package name, current version, CVE identifier, and minimum safe version.\n"
        "4. Write a security report with write_file if requested.\n"
        "5. Call submit_dependency_security_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="dependency_security_agent",
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

    # MASTER_AGENT_v2.md Phase 3.4 gap-closure (2026-07-28) - final_state["result"]
    # (graph-enforced, enforce_in_result-overridden) must win over the handler-
    # captured `result` dict, which is the model's raw, un-overridden submit_*
    # claim; the old priority let a false verification claim leak into
    # AgentResult.raw even though .verified itself was already correct.
    raw = final_state["result"] if final_state["result"] else result
    verified = bool(final_state["verification"].get("read")) and bool(
        final_state["verification"].get("audited")
    )

    # Stage 4 Cluster Q — Security slice (2026-08-05). Only compute/persist
    # a score when this run's audit claim is graph-verified grounded
    # (audited, the same flag `verified` above uses) — never build a score
    # on an unverified claim. Independently re-runs pip-audit itself
    # (never parses the LLM's own narrative findings — see
    # app/fleet/security_score.py's module docstring for why) against the
    # real repo's requirements.txt; repo_id resolved via DevTask.repo_id,
    # Cluster O's single source of truth for repo scoping (ADR 006).
    if verified:
        try:
            from app.db.repository import get_task_repo_id_sync
            from app.fleet.security_score import (
                compute_security_score,
                run_pip_audit_json,
                store_security_score,
            )

            pip_audit_result = run_pip_audit_json(repo)
            if pip_audit_result is not None:
                score_result = compute_security_score(pip_audit_result)
                store_security_score(
                    str(task_id), get_task_repo_id_sync(task_id), score_result
                )
        except Exception as exc:
            logger.warning(
                "Stage 4 Cluster Q: failed to compute/persist security_score "
                "for task %s: %s",
                task_id,
                exc,
            )

    return AgentResult(
        summary=str(raw.get("summary", description[:100])),
        findings=list(raw.get("findings", [])),
        files_touched=[],
        verified=verified,
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


# ---------------------------------------------------------------------------
# SCAN phase — Gap-closure Days 49-50 (Stage 2, answers.md Q35 "Dependency
# conflicts: NO — no dependency-conflict-checking tool/agent found (a
# separate dependency_agent.py/dependency_security_agent.py exist but are
# ordinary task-triggered agents, not in the autonomous loop). Plan: add
# dependency-conflict scanning to the periodic scan loop"). Scope note,
# honestly stated: this wires the real, existing CVE-scanning capability
# into the autonomous loop (the same "wire an existing on-demand agent into
# _fleet_agents_scan_loop()" pattern Day 48 established for
# architecture_reviewer) — it does not add a new version-constraint-graph
# SAT-solver-style conflict detector, which doesn't exist anywhere in this
# codebase and would be new-capability work, not a wiring fix. "Dependency
# conflicts" in the audit's own framing groups with dependency_agent.py's
# unautonomous outdated-version detection in the same sentence — the real,
# buildable gap here is autonomy, not a missing conflict-detection algorithm.
# ---------------------------------------------------------------------------

_SCAN_SUBMIT_ENHANCEMENT_TOOL: dict[str, Any] = {
    "name": "submit_enhancement_request",
    "description": "File one scoped dependency security issue (known CVE, vulnerable pinned version) for human review. One issue per request — never bundle multiple findings into one.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "category": {"type": "string", "enum": ["security", "quality"]},
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {"type": "object"},
        },
        "required": ["title", "description", "category", "priority"],
    },
}

_SCAN_CFG = VerificationConfig(
    set_by={"read_file": "read", "bash": "audited"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read", "audited": "audited"},
    initial={"read": False, "audited": False},
    blocking_until={"bash": "read"},
)

_SCAN_TOOLS = READ_ONLY_TOOLS + [
    DEPENDENCY_AUDIT_BASH_TOOL,
    _SCAN_SUBMIT_ENHANCEMENT_TOOL,
]


def make_scan_handlers(repo_path: str, trace_id: str = "") -> dict[str, Any]:
    handlers = make_chat_handlers(repo_path)
    handlers["bash"] = make_dependency_audit_bash_handler(repo_path)
    handlers["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        AGENT_CONTRACT["name"], trace_id=trace_id
    )
    return handlers


def run_dependency_security_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — autonomous CVE audit of the platform's own dependencies.
    Called periodically from app.main::_fleet_agents_scan_loop(), same as
    the other fleet self-improvement agents' own scan functions."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_scan_handlers(repo, trace_id=trace_id)
    msg = (
        "Autonomous dependency security scan of this codebase. Read requirements.txt / "
        "package.json / lockfiles to identify all real dependencies, then use bash "
        "(pip-audit / npm audit) to check for known CVEs against the real pinned "
        "versions. For each distinct real vulnerability found, file a separate "
        "submit_enhancement_request (category='security') citing the package name, "
        "current version, CVE identifier, and minimum safe version from this run's "
        "real tool output — never a fabricated or generic finding. If nothing real "
        "turns up, that's a normal outcome — don't invent an issue."
    )

    final_state = run_agent_graph(
        role_name="dependency_security_agent",
        model=settings.model_coder,
        tools=_SCAN_TOOLS + [RECORD_LEARNING_TOOL],
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Dependency CVE scan",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=15,
        trace_id=trace_id,
    )

    return AgentResult(
        summary=(
            "Dependency security scan complete"
            if final_state["submitted"]
            else "Dependency security scan complete — nothing to flag"
        ),
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("audited"))
        or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
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
                capabilities=["dependency_vulnerability_scan"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
