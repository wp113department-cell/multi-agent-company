"""Infra Agent — reviews cloud infrastructure code (Terraform, K8s, Docker)."""
from __future__ import annotations
from typing import Any
from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

_SUBMIT = {"name": "submit_infra_review", "description": "Submit infrastructure review findings.", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}, "findings": {"type": "array", "items": {"type": "string"}}, "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]}, "recommendations": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "findings", "severity"]}}
_TOOLS = READ_ONLY_TOOLS + [_SUBMIT]
_CFG = VerificationConfig(set_by={"read_file": "files_read", "search_code": "files_read"}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={"files_read": False})

def make_infra_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}
    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp); return f"Infra review submitted: {len(inp.get('findings', []))} findings"
    base["submit_infra_review"] = submit_h; base["_result"] = result
    return base

def run_infra_agent(task_id: int, description: str, repo_path: str | None = None, on_heartbeat: Any = None, on_tool_call: Any = None) -> AgentResult:
    settings = get_settings(); repo = repo_path or str(settings.target_repo_path)
    handlers = make_infra_handlers(repo); result = handlers["_result"]
    msg = (f"Task #{task_id} — Infrastructure Review\n\n{description}\n\nProcess:\n1. Use get_file_tree to find Terraform (.tf), Kubernetes (.yaml/.yml), Docker, and CI/CD files.\n2. Read each config file with read_file.\n3. Check for: hardcoded secrets, missing resource limits, insecure network rules, missing health checks, non-pinned image versions.\n4. Call submit_infra_review with findings, severity, and recommendations.")
    final_state = run_agent_graph(role_name="infra_agent", model=settings.model_coder, tools=_TOOLS, tool_handlers=handlers, verification_cfg=_CFG, initial_message=msg, max_turns=20)
    raw = result if result else final_state["result"]
    return AgentResult(summary=str(raw.get("summary", "")), findings=list(raw.get("findings", [])), files_touched=[], verified=bool(final_state["verification"].get("files_read")), requires_human_approval=False, tokens_in=final_state["tokens_in"], tokens_out=final_state["tokens_out"], status="completed" if final_state["submitted"] else "blocked", raw=raw)
