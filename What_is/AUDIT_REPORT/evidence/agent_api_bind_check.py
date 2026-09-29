"""Evidence script (Audit 02/12): for every agent dispatchable through
POST /api/agents/{name}/run, bind the EXACT kwargs the endpoint builds
(_agent_call_kwargs) against the agent function's real signature. A bind
failure means the endpoint raises TypeError on every call to that agent.
Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/agent_api_bind_check.py"""
import inspect, os, sys
sys.path.insert(0, os.getcwd())
from app.fleet import capability_registry as cr
cr.ensure_all_agents_registered()
from app.api import specialized_agents as sa
names = sorted(set(sa._REGISTRY) | set(sa._discoverable_agent_names()))
bad = []
for n in names:
    fn = sa._load_agent_fn(n)
    kw = sa._agent_call_kwargs(fn, 1, "probe", "/tmp/x")
    try:
        inspect.signature(fn).bind(**kw)
    except TypeError as e:
        bad.append((n, f"{fn.__module__}.{fn.__name__}", str(e)))
print(f"dispatchable agents checked: {len(names)}; signature bind failures: {len(bad)}")
for b in bad: print("  FAIL", *b)
