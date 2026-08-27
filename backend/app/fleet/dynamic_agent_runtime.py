"""Dynamic agent runtime registry.

Every real dispatch call site resolves an agent to a runnable function
statically: specialized_agents.py imports a module named after the agent
(app/api/specialized_agents.py:_discover_agent_fn), delegation.py looks the
name up in a hand-curated adapter dict (app/agents/delegation.py:
_build_adapter_registry), and manager.py hardcodes "frontend_dev"/
"backend_dev". None of these can find an agent that was registered at
runtime rather than as a module on disk.

This module is the missing piece: a small, generic, thread-safe
name -> callable registry, populated by whatever spawns a runtime agent
(today, exclusively app.agents.temporary_agent's TemporaryAgentPool) and
consulted as a fallback by the real dispatch call sites before they raise/
404 on an unresolvable name. Deliberately generic in name and shape (not
"barot_agent_runtime" or similar) so any future runtime-registered agent
can reuse it without a new mechanism.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

# (task_id, description/objective, repo_path) -> AgentResult — matches the
# shape specialized_agents.py's _agent_call_kwargs() already introspects for
# and delegation.py's own adapter callables.
RuntimeAgentFn = Callable[[int, str, str], Any]

_lock = threading.Lock()
_runtime_fns: dict[str, RuntimeAgentFn] = {}


def register_runtime_agent_fn(name: str, fn: RuntimeAgentFn) -> None:
    with _lock:
        _runtime_fns[name] = fn


def unregister_runtime_agent_fn(name: str) -> None:
    """No-op if absent — safe to call unconditionally during teardown."""
    with _lock:
        _runtime_fns.pop(name, None)


def resolve_runtime_agent_fn(name: str) -> RuntimeAgentFn | None:
    with _lock:
        return _runtime_fns.get(name)
