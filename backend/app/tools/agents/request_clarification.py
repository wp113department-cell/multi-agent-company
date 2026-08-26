"""request_clarification tool — tool_enhance.md productionization pass,
tool #117 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: request_clarification
Old path: app/agents/tools.py (`REQUEST_CLARIFICATION_TOOL` schema dict
    and `make_request_clarification_handler()` factory).
New path: app/tools/agents/request_clarification.py (this file) — same
    names, moved verbatim.
Affected agents: per `AGENT_CONTRACT["allowed_tools"]`, `coder.py` and
    `planner.py` — genuinely ONE real implementation (a single factory
    function, parametrized per calling agent's own name and task_id),
    not two separate ones; confirmed by reading both real call sites'
    actual arguments (`app/agents/coder.py:161`,
    `app/agents/planner.py:157`), not just their count. This tool is
    deliberately NOT in `CHAT_TOOLS` — verified `chat_agent.py` has zero
    reference to it — it is scoped to `run_agent_graph`-based one-shot
    worker agents that lack the checkpointer/interrupt() machinery a
    true mid-run pause would need (see this module's own design-note
    comment below); this is a correct, intentional absence, not a
    missed dispatch (the "advertised but never dispatched" bug class
    found repeatedly this initiative does not apply here since it was
    never advertised to chat in the first place).
Affected modules: app/agents/tools.py (re-exports both names for the 2
    real call sites).
Affected registries: none — app/fleet/tool_manifest.py's
    "request_clarification" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via `make_request_clarification_handler(...)`
    (6 existing test files, all re-run and confirmed passing unchanged).

Runtime verification: PASS — see
    backend/docs/tool_productionization/request_clarification.md.
---------------------------------------------------------------------------

Audited for the finding classes this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched, silent documented-contract
divergence) — none apply. `question`/`context`/`options`/
`recommended_option` reach `request_human_input()` as plain structured
data, stored via the ORM (`PendingApproval`, a JSON `details` column)
through `record_pending()` — never string-interpolated into raw SQL or
a shell command, and there is no filesystem path or network destination
anywhere in this tool's input schema, so there is no worktree-escape or
SSRF surface either. `agent_name`/`task_id` (the values that matter for
attribution integrity) are NEVER LLM-controlled — both real call sites
pass the calling agent's own fixed name and the graph's own numeric
task id as `make_request_clarification_handler(agent_name, task_id)`
arguments, not through `inp`. `record_pending()`'s sync/async bridge
(`app/fleet/approval_gate.py::_record_pending`) already uses
`_new_isolated_db_engine()`, matching this initiative's own established
"never `asyncio.run()` against the shared `app.db.session` engine from
sync code" rule — already correct, not a violation. Handler failures
are already caught and reported as an `[ERROR]` string, never raised
(verified via the existing `test_handler_failure_is_reported_not_raised`
test). No fix required; this turn is pure modularization plus real
verification that the above holds, not assumed from reading alone.
"""

from __future__ import annotations

from typing import Any, Callable

# ---------------------------------------------------------------------------
# request_clarification — MASTER_AGENT_v2.md Phase 5.3. Real, but scoped to
# what base_graph.py (the graph every worker agent besides pm/architect/
# decomposer runs on) can actually support today: it has no checkpointer or
# interrupt()/Command(resume=...) machinery of its own (that only exists in
# app/pipeline/graph.py's separate pm->architect->decomposer pipeline — a
# genuinely different graph). A true mid-run pause/resume for base_graph.py
# agents is graph-level work (Phase 5.1/5.5's territory, not a single tool).
# This is the real, working version that fits the existing shape instead:
# the agent ends its run cleanly (status="needs_clarification", not a silent
# hang or a crash) after recording a real PendingApproval row through the
# same table/mechanism app/fleet/approval_gate.py already uses for the
# pm/architect/decomposer pipeline's own human_review pause — a caller that
# re-dispatches the agent with the human's answer folded into a fresh
# initial_message is how "resume" works for this graph shape.
# ---------------------------------------------------------------------------

REQUEST_CLARIFICATION_TOOL: dict[str, Any] = {
    "name": "request_clarification",
    "description": (
        "Use ONLY when the task is genuinely underspecified and continuing would "
        "mean guessing at something a human should decide — not for every minor "
        "judgment call (a reasonable, disclosed assumption is almost always "
        "better than stopping to ask). Ends this run; a human or upstream agent "
        "answers, and a future run receives that answer in its task context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific, genuine blocker — not a vague 'is this ok?'",
            },
            "context": {
                "type": "string",
                "description": "What you already tried/considered, so the answer doesn't have to re-derive it.",
            },
            # AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) — "Present options
            # (multi-choice): NO" / "Recommend choices: PARTIAL — no
            # structured recommendation field." Optional and additive: a
            # human/upstream-agent reviewer answering via
            # app.fleet.approval_gate's existing PendingApproval row now
            # sees these as structured fields (not just prose buried in
            # `context`), without changing this tool's "ends the run, a
            # future run receives the answer" scope at all.
            "options": {
                "type": "array",
                "description": "Optional: 2-5 distinct choices, if the blocker is genuinely 'pick one of these'.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
            },
            "recommended_option": {
                "type": "string",
                "description": "Optional: id of the option you'd recommend, if any.",
            },
        },
        "required": ["question"],
    },
}


def make_request_clarification_handler(
    agent_name: str, task_id: str = ""
) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for request_clarification, scoped to the
    calling agent's own name and task so the recorded row is correctly
    attributed and findable by a real human/upstream-agent review flow."""

    def _handler(inp: dict[str, Any]) -> str:
        question = str(inp.get("question", "")).strip()
        if not question:
            return "[ERROR] question is required."
        context = str(inp.get("context", "")).strip()
        options = inp.get("options") or None
        recommended_option = inp.get("recommended_option") or None

        from app.fleet.approval_gate import request_human_input

        try:
            request_human_input(
                kind="clarification",
                details={
                    "question": question,
                    "context": context,
                    "options": options,
                    "recommended_option": recommended_option,
                },
                agent_name=agent_name,
                thread_id=f"clarify-{task_id or 'notask'}-{agent_name}",
                task_id=int(task_id) if str(task_id).isdigit() else None,
                blocking=False,
                description=f"{agent_name} requested clarification: {question[:200]}",
            )
        except Exception as exc:
            return f"[ERROR] failed to record clarification request: {exc}"
        return "Clarification request recorded. Ending this run to await an answer."

    return _handler
