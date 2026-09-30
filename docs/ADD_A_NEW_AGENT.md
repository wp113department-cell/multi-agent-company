# How to Add a New Agent — Gridiron Developer Department

A complete walkthrough for adding a production-grade LangGraph agent from scratch. Estimated time: ~2 hours for a new agent with full test coverage.

---

## 1. Create the agent module

Create `backend/app/agents/{your_agent_name}.py`.

Copy this template and fill in the blanks:

```python
"""Your Agent Name — one-line description.

Verification contract:
  - <key>: set True when <tool_name> tool is actually called
"""
from __future__ import annotations
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings


# ── Submit tool ────────────────────────────────────────────────────────────────
_SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_<your_agent>_result",
    "description": "Submit the final result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            # ... add your result fields here
        },
        "required": ["summary"],
    },
}

# ── Tool list ──────────────────────────────────────────────────────────────────
_YOUR_AGENT_TOOLS = READ_ONLY_TOOLS + [
    # Add write_file, run_bash, etc. if the agent needs them.
    # Keep it minimal — agents should not have tools they don't need.
    _SUBMIT_TOOL,
]

# ── Verification contract ──────────────────────────────────────────────────────
# Which tool call sets which verification key True?
# This is enforced by the graph: verified=True ONLY when the tool was actually called.
_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "codebase_read",          # example: reading code sets codebase_read
        # "write_file": "file_written",        # example: writing code sets file_written
    },
    reset_by=(),      # leave empty unless a tool call should reset verification
    reset_keys=(),
    enforce_in_result={},
    initial={"codebase_read": False},          # must match keys in set_by values
)


# ── Handler factory ────────────────────────────────────────────────────────────
def make_your_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Extend make_chat_handlers with this agent's custom submit handler."""
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        return f"Result submitted: {inp.get('summary', '?')[:100]}"

    base["submit_<your_agent>_result"] = submit_h
    base["_your_agent_result"] = submitted   # internal state — prefix with _ so tests skip it
    return base


# ── Entry point ────────────────────────────────────────────────────────────────
def run_your_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_your_agent_handlers(repo)
    submitted = handlers["_your_agent_result"]

    message = (
        f"Task #{task_id} — Your Agent\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file / search_code to understand context — MANDATORY.\n"
        "2. [Describe what the agent should do]\n"
        "3. Call submit_<your_agent>_result when complete."
    )

    final_state = run_agent_graph(
        role_name="your_agent_name",        # matches backend/roles/<name>.md
        model=settings.model_coder,         # or model_planner for lighter tasks
        tools=_YOUR_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = submitted if submitted else final_state["result"]
    return AgentResult(
        summary=raw.get("summary", "No summary"),
        findings=[],                        # list[dict] — each finding is a dict
        files_touched=[],
        verified=bool(final_state["verification"].get("codebase_read", False)),
        requires_human_approval=False,      # set True when human review is needed
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
```

---

## 1b. Register the agent with the fleet (required — updated 2026-09-29)

The code now enforces these; an agent missing any of them either never appears
in the fleet or fails a guard test:

1. **`AGENT_CONTRACT` dict + `_register()` called at import.** Copy the shape
   from an existing agent (e.g. `app/agents/sql_agent.py`): `name` (= module
   name), `description`, `allowed_tools` (every **high-risk** tool the agent is
   given must be listed here, or `filter_runtime_tools` silently removes it),
   `input_types`, `output_types`, `side_effects`, `permissions`,
   `risk_level`, `expected_verification`, `dependencies`. `_register()` calls
   `capability_registry.register(AgentCapability(...))` and
   `get_agent_registry().register(name)`. Capability tags must be unique
   fleet-wide.
2. **A row in `backend/app/fleet/agent_models.json`** (model + tier).
   `tests/test_audit02_specialized_agent_call_contract.py` fails if any
   registered agent has no explicit row.
3. **Standalone signature:** `run_your_agent(task_id, description, repo_path=None, …)`.
   `/api/specialized-agents/{name}/run` fills `task_id`, the description
   (parameter named `description`, `task_description` or `doc_request`) and
   `repo_path` by **name**; an agent that needs more (a plan, a worktree, a
   diff) is refused with 422 and can only run inside the task pipeline.
   Pass `task_id=str(task_id)` into `run_agent_graph()` so live activity
   events reach the task.
4. **Write scope matches `permissions`.** A `write_docs` agent must not get the
   unscoped `write_file` from `make_chat_handlers()` — wrap it with
   `app.agents.tool_security.docs_or_new_file_write_denial` (see
   `api_designer_agent.py`).
5. The agent is auto-discovered by `/api/specialized-agents` if its module has
   `AGENT_CONTRACT` and exactly one public `run_*` function — adding it to
   `_REGISTRY` (section 3) is only needed for a short alias name.

---

## 2. Create the role file

Create `backend/roles/your_agent_name.md`.

This is the system prompt loaded at runtime. It must:
- State the agent's role and responsibilities
- Define the expected process (numbered steps)
- State what the submit tool is called and when
- List any constraints (read-only, no deploy, etc.)

See `backend/roles/security_architect.md` for a well-structured example.

---

## 3. (Optional) Add a short alias in the dispatch registry

Only needed for an alias name — the module name is auto-discovered (section 1b). Open `backend/app/api/specialized_agents.py` and add one line to `_REGISTRY`:

```python
_REGISTRY: dict[str, tuple[str, str]] = {
    # ... existing agents ...
    "your_agent_name": ("app.agents.your_agent_name", "run_your_agent"),
}
```

The key is the URL slug (`/api/specialized-agents/your_agent_name/run`).

---

## 4. Write tests

Create `backend/tests/test_your_agent.py`:

```python
from app.agents.your_agent_name import (
    run_your_agent,
    make_your_agent_handlers,
    _VERIFICATION_CFG,
    _YOUR_AGENT_TOOLS,
)
from app.agents.tools import READ_ONLY_TOOLS
from app.agents.base_graph import VerificationConfig
from pathlib import Path

_REPO = str(Path(__file__).parent.parent.parent)

def _tool_names(tools):
    return {t["name"] for t in tools}

class TestYourAgentTools:
    def test_includes_read_only_tools(self):
        read_only = {t["name"] for t in READ_ONLY_TOOLS}
        assert read_only.issubset(_tool_names(_YOUR_AGENT_TOOLS))

    def test_includes_submit_tool(self):
        assert "submit_<your_agent>_result" in _tool_names(_YOUR_AGENT_TOOLS)

    def test_all_tools_have_required_fields(self):
        for tool in _YOUR_AGENT_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool

class TestYourAgentVerification:
    def test_is_verification_config(self):
        assert isinstance(_VERIFICATION_CFG, VerificationConfig)

    def test_initial_state(self):
        assert "codebase_read" in _VERIFICATION_CFG.initial

class TestYourAgentHandlers:
    def test_handlers_not_empty(self):
        h = make_your_agent_handlers(_REPO)
        assert len(h) > 0

    def test_submit_handler_present(self):
        h = make_your_agent_handlers(_REPO)
        assert "submit_<your_agent>_result" in h

    def test_handlers_are_callable(self):
        h = make_your_agent_handlers(_REPO)
        for name, fn in h.items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_stores_result(self):
        h = make_your_agent_handlers(_REPO)
        h["submit_<your_agent>_result"]({"summary": "Test result"})
        assert h["_your_agent_result"]["summary"] == "Test result"

class TestRegistryWiring:
    def test_agent_in_registry(self):
        from app.api.specialized_agents import _REGISTRY
        assert "your_agent_name" in _REGISTRY

    def test_load_fn_works(self):
        from app.api.specialized_agents import _load_agent_fn
        fn = _load_agent_fn("your_agent_name")
        assert callable(fn)

class TestRoleFile:
    def test_role_file_exists(self):
        from pathlib import Path
        roles_dir = Path(__file__).parent.parent / "roles"
        assert (roles_dir / "your_agent_name.md").exists()
```

Run: `pytest tests/test_your_agent.py -v` — all should pass.

---

## 5. Run the full test suite

```bash
cd backend
pytest tests/ -q
```

All 934+ tests must pass before merging.

---

## 6. Verify the endpoint works

```bash
# Start the backend
uvicorn app.main:app --reload

# In another terminal, test the endpoint
curl -X POST http://localhost:8000/api/specialized-agents/your_agent_name/run-sync \
  -H "Content-Type: application/json" \
  -d '{"task_id": 1, "description": "Test run"}'
```

Expect a `RunAgentResponse` JSON with `status`, `summary`, `verified`, `tokens_in`, `tokens_out`.

---

## Checklist

- [ ] `backend/app/agents/your_agent_name.py` — module with `run_*`, `make_*_handlers`, `_VERIFICATION_CFG`, `_*_TOOLS`
- [ ] `AGENT_CONTRACT` + `_register()` at import; high-risk tools listed in `allowed_tools`
- [ ] Row in `backend/app/fleet/agent_models.json`
- [ ] `backend/roles/your_agent_name.md` — system prompt role file with the 7 role sections: Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract, Quality Gates, Edge Cases, Escalation
- [ ] (Optional) alias entry in `_REGISTRY` in `backend/app/api/specialized_agents.py` — auto-discovery covers the module name
- [ ] Tests in `backend/tests/test_your_agent.py` — all passing
- [ ] Full test suite still green (`pytest tests/ -q`)
- [ ] `findings` field uses `list[dict]`, not `list[str]`
- [ ] `requires_human_approval=True` if agent produces recommendations that change production state
- [ ] Agent is read-only if it should not write files (no `write_file` in tool list)

---

## Key invariants (never break these)

1. `verified=True` is set from `final_state["verification"]`, never from the model's own claim.
2. The submit tool handler stores to a `submitted` dict, and `run_*()` reads from that dict — not from `final_state["result"]` alone.
3. Handler dict keys prefixed with `_` are internal state containers, not callable handlers.
4. `findings` must be `list[dict]`, never `list[str]` (enforced by `AgentResult` type annotation).
5. Role file name must exactly match the `role_name` argument to `run_agent_graph()`.
