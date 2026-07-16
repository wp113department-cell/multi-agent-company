"""load_test_agent — LangGraph agent."""
from __future__ import annotations
from typing import Any
from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

_SUBMIT = {"name": "submit_load_test_agent", "description": "Submit load_test_agent result.", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}, "findings": {"type": "array", "items": {"type": "string"}}, "recommendations": {"type": "array", "items": {"type": "string"}}}, "required": ["summary"]}}
_WRITE = {"name": "write_file", "description": "Write output file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}
_TOOLS = READ_ONLY_TOOLS + [_WRITE, _SUBMIT]
_CFG = VerificationConfig(set_by={"read_file": "read", "search_code": "read"}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={"read": False})

def make_load_test_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}
    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp); return "Submitted."
    base["submit_load_test_agent"] = submit_h; base["_result"] = result
    return base

def run_load_test_agent(task_id: int, description: str, repo_path: str | None = None, on_heartbeat: Any = None, on_tool_call: Any = None) -> AgentResult:
    settings = get_settings(); repo = repo_path or str(settings.target_repo_path)
    handlers = make_load_test_agent_handlers(repo); result = handlers["_result"]
    msg = f"Task #{task_id} — {description}\n\nUse available tools to complete this task. Call submit_load_test_agent with your findings and summary when done."
    final_state = run_agent_graph(role_name="load_test_agent", model=settings.model_coder, tools=_TOOLS, tool_handlers=handlers, verification_cfg=_CFG, initial_message=msg, max_turns=20)
    raw = result if result else final_state["result"]
    return AgentResult(summary=str(raw.get("summary", description[:100])), findings=list(raw.get("findings", [])), files_touched=[], verified=bool(final_state["verification"].get("read")), requires_human_approval=False, tokens_in=final_state["tokens_in"], tokens_out=final_state["tokens_out"], status="completed" if final_state["submitted"] else "blocked", raw=raw)
