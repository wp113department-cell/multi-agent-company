# Day 18 Plan — Real-Time Streaming to Frontend (Pipeline Events)

Per `docs/FLEET_ENHANCEMENT_PLAN.md` lines 1197-1225. Goal: live updates as agents run.

## Research (REPO-FIRST)

`repos/opencode/packages/server/src/handlers/event.ts` — confirms the plan's own constants are
real, load-bearing values from a real project: `subscriberCapacity = 256`, a 15-second heartbeat
tick merged into the stream, `Cache-Control: no-cache, no-transform` / `X-Accel-Buffering: no`
headers (disables reverse-proxy buffering so events aren't held back). TypeScript/Effect, not
directly portable, but every numeric constant and header choice is now grounded in a real system,
not guessed.

## Codebase grounding — the central finding

The plan's own note says "Chat agent already has SSE streaming. This day wires the same SSE to the
pipeline agents" — investigated before designing anything, per the standing project lesson (a
feature wired into only one of several real entry points is a real gap, not a false negative;
gap-closure 2026-07-22).

**What already exists, fully working:**
- `app/services/activity_stream.py` — `TaskStream`/`ActivityStreamRegistry`, `push_thinking`/
  `push_tool_call`/`push_tool_result`/`push_file_edit`/`push_terminal`/`push_token_usage`/
  `push_done`/`push_stopped`/`push_error`. Module docstring: "Every `run_agent_graph()` call pushes
  typed events here."
- `app/api/activity.py`'s `GET /api/tasks/{id}/stream` — **already the exact endpoint URL the
  plan asks for**, real `StreamingResponse`, real SSE headers.
- `app/agents/base_graph.py`'s `run_agent_graph()` (the shared core for all 72+ agents) **already
  calls every one of those push_* functions**, gated behind `if task_id:` — confirmed by direct
  grep, not assumed.
- `apps/web/app/stream/[taskId]/page.tsx` — a **complete, already-built, dark-mode-aware activity
  feed UI**: `EventSource` subscription, thinking/tool_call/tool_result/file_edit/terminal/
  token_usage/stopped/done/error rendering, auto-scroll, Stop/Resume controls, token/cost sidebar.

**The real gap, found by tracing every real call site, not assumed clean:** `run_agent_graph()`'s
`task_id` parameter defaults to `""` (falsy), and **every one of the 8 real agent runners —
`pm_node`, `architect_node`, `decomposer_node` (`pipeline/graph.py`'s nodes) and `run_backend_dev`,
`run_frontend_dev`, `run_coder`, `run_qa`, `run_reviewer` (the dev-agent runners) — never passes
`task_id` to `run_agent_graph()` at all**, confirmed by grep across every file. This means the
fully-built activity stream and fully-built frontend feed have never received a single real event
for an actual task pipeline run since the day they were built — only chat sessions (which do pass
a real id) have ever populated it. This is the actual Day 18 work: not building new
infrastructure, but making the existing infrastructure receive real data, plus two smaller,
genuinely-missing pieces:

1. **`push_agent_switch` is documented but was never implemented.** The module's own docstring
   lists `agent_switch — role_name changed mid-pipeline` as a real event type; grep confirms no
   such function exists. Needed for the plan's "pm_node thinking...", "architect planning..."
   node-transition visibility.
2. **No `approval_required` event type exists at all.** The plan's explicit success criterion
   ("Approval gate shows as interactive card in the stream") requires one; nothing currently
   pushes anything when Day 13/14's `pending_approvals` gets a new row.
3. **The task detail page never links to the already-built `/stream/[taskId]` feed.** Confirmed by
   grep — zero references. Reusing the existing, already-tested ~400-line component via a link
   rather than duplicating it into an inline panel (the plan's own pseudocode path,
   `apps/web/src/components/TaskStream.tsx`, doesn't even match this project's real convention —
   `apps/web/components/`, no `src/`).
4. **Heartbeat interval mismatch**: the plan's own success criterion is "heartbeat tested with 16s
   wait," but `activity.py`'s `stream.subscribe(timeout=30.0)` only emits a keep-alive `ping` every
   30s — a 16-second test would see nothing yet. Changed to `15.0`, matching both the plan's stated
   interval and OpenCode's own real constant.

## Design

- Thread `task_id=str(...)` through all 8 `run_agent_graph()` calls (each function already has the
  real task_id in scope — `state["task_id"]` in the three pipeline nodes, `task_id: int` as an
  existing parameter in the five dev-agent runners).
- `activity_stream.py`: add `push_agent_switch(task_id, agent, phase)` and
  `push_approval_required(task_id, thread_id, action)`.
- Call `push_agent_switch` at the top of `pm_node`/`architect_node`/`decomposer_node` and before
  each dev-agent dispatch in `manager.py`'s `run_manager()` loop.
- Call `push_approval_required` right after `arecord_pending()` succeeds in
  `launch_planning_pipeline()` (plan_review) and `_record_git_push_approval()` (git_push) —
  the same two real call sites Day 13/14 already established for the approvals system itself.
- `activity.py`: `timeout=30.0` → `timeout=15.0`.
- Frontend: a "View live activity →" link on the task detail page to `/stream/{id}`.

## Success criteria (from the plan, verified against the real wiring, not assumed)

Start a task → real pipeline events (not just chat) reach the SSE stream keyed by the real task_id
→ node transitions and tool calls appear → a pending approval shows as a real `approval_required`
event → heartbeat observably fires within 16s → tests for the SSE encoder/queue behavior already
exist (`test_activity_stream.py`) and are extended for the two new event types and the real
task_id-threading fix.
