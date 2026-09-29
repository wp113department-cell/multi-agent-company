"""Evidence script (Audit 07): drive the REAL run_agent_graph (only the Anthropic
HTTP call is faked: one tool_use turn, then a submit) and read MetricsCollector
afterwards — proves tokens, tool calls with durations, verification and status
actually reach RunMetrics. Run from backend/."""
import os, sys, tempfile
sys.path.insert(0, os.getcwd())
from unittest.mock import patch
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from app.agents import base_graph
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.fleet.metrics import get_metrics_collector

repo = tempfile.mkdtemp(); open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
calls = {"n": 0}
def fake(client, **kw):
    calls["n"] += 1
    tools = [t["name"] for t in kw.get("tools", [])]
    if "read_file" in tools and calls["n"] <= 3 and not any(
        isinstance(m.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
        for m in kw.get("messages", [])):
        block = ToolUseBlock(type="tool_use", id="t1", name="read_file", input={"path": "a.py"})
        stop = "tool_use"
    elif "submit_probe" in tools:
        block = ToolUseBlock(type="tool_use", id=f"s{calls['n']}", name="submit_probe", input={"summary": "done", "read_ok": True})
        stop = "tool_use"
    else:
        block = TextBlock(type="text", text="ok"); stop = "end_turn"
    return Message(id="m", type="message", role="assistant", model="x", content=[block],
                   stop_reason=stop, stop_sequence=None, usage=Usage(input_tokens=100, output_tokens=20))

tools = [
    {"name": "read_file", "description": "read", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "submit_probe", "description": "submit", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}, "read_ok": {"type": "boolean"}}, "required": ["summary"]}},
]
handlers = {"read_file": lambda inp: open(os.path.join(repo, inp["path"])).read(), "submit_probe": lambda inp: "Submitted."}
cfg = VerificationConfig(set_by={"read_file": "read"}, enforce_in_result={"read_ok": "read"}, initial={"read": False})
with patch.object(base_graph, "_call_anthropic", side_effect=fake):
    final = run_agent_graph(role_name="style_reviewer", model="x", tools=tools, tool_handlers=handlers,
                            verification_cfg=cfg, initial_message="probe", task_description="metrics probe",
                            repo_path=repo, trace_id="audit07-metrics-probe",
                            enable_planning=False, enable_memory=False, enable_reflection=False, enable_lesson=False)
m = get_metrics_collector().get("audit07-metrics-probe")
print("LLM calls:", calls["n"], "| submitted:", final.get("submitted"), "| result.read_ok (graph-enforced):", (final.get("result") or {}).get("read_ok"))
if m is None:
    print("RunMetrics: NOT RECORDED")
else:
    print(f"RunMetrics: status={m.status} tokens_in={m.tokens_in} tokens_out={m.tokens_out} "
          f"verification_pct={m.verification_pct} duration_ms={getattr(m, 'duration_ms', None)}")
    for tc in m.tool_calls:
        print(f"  tool {tc.tool_name} success={tc.success} duration_ms={tc.duration_ms}")
