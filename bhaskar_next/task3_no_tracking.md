# Task 3 — the 14 "NO" items, implemented one by one

Started 2026-09-25, after Task 2 (all 70 PARTIAL items) closed out. User's
own instruction: industry-grade, production-use implementation, easiest/
smallest items first, biggest/hardest last.

Verdicts: `PENDING` · `DONE` · `SKIPPED`

## Scope note — #169/#171/#494 fully skipped, not just deferred

#169 (distributed registries), #171 (horizontal scaling), and #494
(distributed AgentRegistry dispatch coordination) are the same underlying
distributed-systems problem (multi-instance backend coordination) at
different points in the original 519-item audit. User confirmed
(2026-09-25) all three are **fully skipped from this plan** — not "do
last", not "revisit later automatically" — genuinely out of scope unless
the user brings them back explicitly (e.g. once this actually runs more
than one backend instance). #169 was already tracked this way in
`enhance_partial_tracking.md`; #171/#494 are recorded here the same way
and removed from the ordered plan below.

## Ordered plan (12 real items, easiest → hardest)

| Order | Item(s) | Status |
|---|---|---|
| 1 | #500 Conversational "do that again" | DONE |
| 2 | #44 Agents create subtasks dynamically | DONE (real gap fixed; flag stays off pending user decision) |
| 3 | #454 Dependency checks as mandatory gate | PENDING |
| 4 | #457 Documentation checks as mandatory gate | PENDING |
| 5 | #297 Auto documentation lookup while coding | PENDING |
| 6 | #58 Agent selection uses memory/past outcomes | PENDING |
| 7 | #405 Company Brain (org knowledge for prompts/tools) | PENDING |
| 8 | #66 Switch tools mid-run | PENDING |
| 9 | #443 Detect hallucinating/leaking/desynced agents | PENDING |
| 10 | #45 + #67 Agent-to-agent delegation | PENDING |
| 11 | #227 Human takeover / step-level plan editing | PENDING |
| — | #169 + #171 + #494 Distributed registry / horizontal scaling | SKIPPED (user decision, all three) |

## #500 — Conversational "do that again" — DONE (2026-09-25)

Reused the existing deterministic task-repeat mechanism
(`POST /api/tasks/{id}/repeat` → `repeat_task()`) rather than building a
second one. Extracted the real orchestration (`repeat_task()` + transition
+ log + dispatch) out of the HTTP route into a new shared function
`repeat_and_dispatch_task()` (`app/api/tasks.py`) so both the HTTP route
and the new chat tool call the exact same real path — not two
independently-maintained copies. The chat tool has no real
`BackgroundTasks` in scope (no HTTP request), so it uses
`app.main._FireAndForgetBackgroundTasks` — the same shim #429's own
periodic dependency-auto-dispatch loop already built for this identical
problem, not a new one.

Two new chat tools (`app/agents/tools.py`, dispatched in
`app/agents/chat_agent.py`):
- `find_repeatable_tasks` — real candidates from `dev_tasks`, scoped to
  the chat session's own `repo_id`. Never resolves ambiguity itself: when
  more than one candidate matches, its own returned text explicitly
  instructs the model to call `ask_human_to_choose` before repeating
  anything — "never silently guess" enforced by the tool's own output,
  not left to prompt-level judgement alone.
- `repeat_previous_task` — requires a specific `task_id` (no "just repeat
  the most recent one" shortcut exists), so by construction the model
  must have already resolved which task it means — either unambiguously
  from `find_repeatable_tasks`, or via a real `ask_human_to_choose` pause
  — before this tool can be called at all. Supports `description_override`
  for "repeat it but change X" requests.

`roles/chat.md` updated with the expected usage pattern.

Tests: `tests/test_chat_repeat_task.py` (9 tests, real Postgres — real
Repo/DevTask rows, no mocked DB) — unambiguous match, ambiguous match,
zero matches, cross-repo isolation (a task in a different repo never
shows up as a candidate), real clone+dispatch, description override,
missing/invalid task_id errors, and one full graph-level test proving the
LLM-driven ambiguous flow end-to-end with a fake Anthropic stream (same
pattern as `test_phase52_chat_graph_interrupt.py`) — confirms the graph
genuinely pauses at a real `interrupt()` before repeating anything, and
only repeats after the human's choice resolves it.

Regression: 30/30 on the direct test set, 850/850 on a broader
chat_agent/repeat_task/task sweep. Full backend suite pending re-run
after a mid-session power outage interrupted the previous one (Docker/
Postgres/Redis recovered automatically once Docker Desktop was
restarted).

## #44 — Agents create subtasks dynamically — DONE (2026-09-25)

**Real finding before writing anything**: this item was already
extensively built by an EARLIER, separate initiative
("plan14 follow-on #2", predating this Task 1/Task 2/Task 3 thread) —
`app/pipeline/dynamic_subtasks.py` (validation: allow-matrix, depth cap,
count cap, duplicate-title/files rejection; real file-lock reservation
via the existing `reserve_epic_files()`; wave-boundary integration into
`run_manager()`'s own dispatch loop, refilling the wave queue so new work
is discovered without restarting the epic), `app/tools/agents/
propose_subtask.py` (the real tool), and 30 existing tests
(`tests/test_dynamic_subtask_creation.py`). Sitting behind
`Settings.dynamic_subtask_creation_enabled_agents` — empty by default,
same "built but zero consumers" shape as #12 before today.

This matches the audit's own rule: "if the current source shows that an
old gap has already been fixed, do not recreate it. Verify it and move to
the remaining gap." Verifying now, not rebuilding from scratch.

**Real gap confirmed by direct reading (`app/agents/manager.py:913`)**: a
dynamically-integrated subtask NEVER gets a real `Subtask` DB row created
for it — `_dispatch_one_subtask`'s own status-persistence line
(`if db is not None and subtask_idx < len(db_subtask_rows):`) is
unconditionally False for any index beyond the original static count.
Concretely: a dynamically-proposed subtask is invisible to
`GET /api/tasks/{id}/subtasks`, and a crash mid-epic after it was
integrated (or even mid-dispatch) leaves zero DB trace it ever existed —
the "persist enough state for crash/recovery" requirement from the
original audit item is not met. This is the one real gap to fix; the
"respect existing token/cost budget" requirement is judged satisfied by
the existing `dynamic_subtask_max_per_epic`/`dynamic_subtask_max_depth`
caps — there is no other epic-level $ budget mechanism anywhere in this
codebase to plug into, and building one from scratch is out of scope for
this specific item.

**Fix applied**: `app/db/repository.py::add_subtask()` (new) — single-row
counterpart to the existing bulk `save_subtasks()`, same field mapping,
same 0-based-index `depends_on` convention (confirmed not a real foreign
key despite the `ARRAY(BigInteger)` column type — `save_subtasks()`
already passes indices straight through with no translation).
`app/pipeline/dynamic_subtasks.py::integrate_proposals()` gained optional
`task_id`/`db_subtask_rows` params — when given, a real `Subtask` row is
created for every integrated proposal, attempted BEFORE the in-memory
`subtasks.append()` (not after): if persistence fails, the WHOLE proposal
is rejected rather than partially degraded, because `db_subtask_rows` must
stay in exact position-lockstep with `subtasks` — that positional
correlation is the ONLY link `_dispatch_one_subtask`'s own status-
persistence check has (the decomposer's transient "id" field is not the
real DB primary key). `app/agents/manager.py`'s one real call site now
passes both. Backward compatible: both params default `None`, and a third
new test proves every pre-existing caller that omits them gets the exact
original in-memory-only behavior, unchanged.

Tests: 3 new in `tests/test_dynamic_subtask_creation.py` (persists a real
row + position lockstep verified against real Postgres; rejects cleanly
and keeps lockstep on a simulated persistence failure; zero-behavior-
change proof for callers without task_id) — all 38 tests in that file
pass (35 pre-existing + 3 new), zero regressions. Full backend suite:
8668 passed, 6 failed — 5 match the exact known pre-existing baseline,
1 (`test_gap54_phase_timing.py`) reproduced passing standalone (confirmed
order/resource-dependent flake, unrelated to this change).

**Deliberately left for the user to decide, not flipped unilaterally**:
`dynamic_subtask_creation_enabled_agents` stays empty (off) by default.
Turning it on for `backend_dev`/`frontend_dev` (already policy-configured
in `dynamic_subtask_allowed_matrix` and tool-wired — literally one config
change away) would let real autonomous agents spawn genuinely new work
mid-epic without a human approving it first — a real increase in agent
autonomy and cost exposure, not a pure UX/streaming toggle like #12's own
flag flip. The audit's own original characterization of this item
("highest-risk item in the backlog... genuine risk of destabilizing an
existing, working invariant if rushed") plus its own recommended rollout
("enabled only for specific epics/agents initially") both argue for
asking rather than deciding this one alone.
