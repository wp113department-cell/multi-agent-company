"""T2-B2 (2026-09-22, GRIDIRON_PARTIAL #212/#213/#235/#236/#246) — the
per-agent-type graph-rebuild registry the audit's own plan calls for:

    "Build a per-agent-type graph-rebuild registry: a factory that maps
    agent_type (coder, backend_dev, qa, ...) to the correct
    tool_handlers/verification_cfg combination for that agent, since each of
    the ~76-83 worker-agent files currently builds these inline rather than
    from a shared registry."

Rather than inventing a second, parallel registry, this reuses
app.api.specialized_agents.py's existing `_load_agent_fn()`/
`_agent_call_kwargs()` — already built and proven (Task 1, batch B7) to
dynamically resolve an agent_type string to its real run_* function and
correctly build that function's call kwargs (including the Day 53 fix for
functions whose second positional parameter isn't literally named
`description`). That IS the per-agent-type factory this item asks for; it
just didn't yet have a resume path threaded through it.

Coverage is deliberately bounded and self-documenting rather than guessed:
an agent is resumable through this registry if and only if its run_*
function's signature declares a `resume_trace_id` parameter — added, so far,
to a representative first slice of the ~65 specialized-agents.py registry
entries (bug_fix, readme_agent, api_docs_agent, sql_agent, cleanup_agent,
cicd_agent — chosen to cover the registry's real parameter-name diversity:
error_description/doc_request/task_description/description). Extending
coverage to the remaining agents is the exact same two-line change proven
here (add `resume_trace_id: str = ""` to the signature, thread it into that
agent's own run_agent_graph(...) call) repeated per file — additive, no risk
to already-covered agents, and intentionally left as incremental follow-up
rather than a single mechanical sweep across ~60 more heterogeneous files
in one pass (the same "start with the highest-value slice, prove it, roll
the rest out incrementally" approach the audit's own plan already uses for
#255/#453/#455). An agent NOT yet covered returns None here — the caller
(the /resume endpoint, reconcile_orphaned_runs()) falls back to its existing,
honest pre-T2-B2 behavior for it, never a guessed/fabricated resume.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def is_resumable_agent_type(agent_type: str) -> bool:
    """True iff agent_type resolves to a real run_* function that declares
    a resume_trace_id parameter — the single, mechanically-checkable
    coverage marker this registry uses instead of a separately-maintained
    allowlist (see module docstring)."""
    try:
        fn = _load_agent_fn_or_none(agent_type)
    except Exception:
        return False
    return fn is not None and "resume_trace_id" in inspect.signature(fn).parameters


def _load_agent_fn_or_none(agent_type: str) -> Callable[..., Any] | None:
    from app.api.specialized_agents import _load_agent_fn

    try:
        return _load_agent_fn(agent_type)
    except ValueError:
        return None


def resolve_resume_call(
    agent_type: str,
    task_id: int,
    trace_id: str,
    resume_message: str,
    repo_path: str,
) -> tuple[Callable[..., Any], dict[str, Any]] | None:
    """Resolves agent_type to (fn, kwargs) ready to call as `fn(**kwargs)`
    (dispatch it via asyncio.to_thread, exactly like
    app.api.specialized_agents._run_specialized_agent_bg already does for a
    fresh dispatch) — or None if agent_type isn't a real, resumable agent.

    resume_message becomes whatever this agent's own second positional
    parameter is (error_description / doc_request / task_description /
    description / ...) — reusing _agent_call_kwargs' own introspection means
    this registry never needs its own hardcoded name for it. For an
    interactive Resume (a human's follow-up note), that's exactly right; for
    orphan-recovery, the caller passes the ORIGINAL task's own
    description/plan text as resume_message, so the wrapper's usual message
    template still frames the turn sensibly.
    """
    from app.api.specialized_agents import _agent_call_kwargs

    fn = _load_agent_fn_or_none(agent_type)
    if fn is None:
        logger.info(
            "resume_registry: %r does not resolve to a real agent function",
            agent_type,
        )
        return None

    if "resume_trace_id" not in inspect.signature(fn).parameters:
        logger.info(
            "resume_registry: %r (%s) has no resume_trace_id parameter yet — "
            "not resumable through this registry",
            agent_type,
            getattr(fn, "__name__", fn),
        )
        return None

    kwargs = _agent_call_kwargs(fn, task_id, resume_message, repo_path)
    kwargs["resume_trace_id"] = trace_id
    return fn, kwargs
