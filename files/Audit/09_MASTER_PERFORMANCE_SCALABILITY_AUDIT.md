# MASTER PERFORMANCE & SCALABILITY AUDIT

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.

You are a Principal Performance Engineer + Principal Infrastructure Engineer.
Audit this system's behavior under load — concurrency, cost, token usage,
and resource bounds — using real code evidence, not speculation. Where real
load testing isn't possible in this environment, be explicit that a finding
is "static analysis only, not load-tested" rather than presenting it as
verified.

## PHASE 0 — Orientation

Read:
- `backend/app/pipeline/concurrency.py` — semaphore definitions and limits
- `backend/app/fleet/budget_manager.py` — per-run and daily budget
  enforcement (tokens, time, memory via `resource.getrusage`)
- `backend/app/config.py` — `MAX_CONCURRENT_EPICS`,
  `MAX_CONCURRENT_AGENT_RUNS`, `MAX_CONCURRENT_SUBTASKS_PER_EPIC`,
  `MAX_TOKENS_PER_AGENT_RUN`, `COST_BUDGET_DAILY_USD`,
  `MAX_RUN_TIME_SECONDS`, `MAX_MEMORY_MB`
- `backend/app/agents/base_graph.py` — `_trim_messages` (context
  window/token budget enforcement), stall detection
- `backend/app/pipeline/cost_controller.py` — pre-flight cost estimation
- `backend/app/repo_tools/context_builder.py` — in-memory caching
- Every `async def` handler that calls a synchronous/blocking library
  function without `asyncio.to_thread()` — this is a real class of bug to
  hunt for actively.

## PHASE 1 — Concurrency Correctness

- Confirm semaphores (`epic_slot`, `agent_run_slot`,
  `subtask_slot(epic_id)`) are ACTUALLY acquired around the real dispatch
  code paths (not just defined) — trace each into `manager.py` / API
  routes.
- Assess whether the configured default limits are internally consistent
  (e.g. can `MAX_CONCURRENT_SUBTASKS_PER_EPIC × MAX_CONCURRENT_EPICS`
  exceed `MAX_CONCURRENT_AGENT_RUNS` in a way that causes epics to silently
  starve rather than fail loudly)?
- Confirm `conflict_guard.check_file_conflicts()` doesn't become an
  O(n²) bottleneck as the number of concurrently running epics grows (what
  does it actually query, and how often is it called per subtask?).

## PHASE 2 — Blocking Call Audit

Grep the entire `backend/app/` tree for synchronous, potentially-blocking
operations inside `async def` functions without `asyncio.to_thread()` or an
async-native equivalent:
- Synchronous `subprocess.run`/`os.system` calls
- Synchronous file I/O on potentially large files
- Synchronous `requests.*` calls (vs `httpx.AsyncClient`)
- Synchronous embedding/LLM SDK calls where an async client exists
For each one found, report file:line and assess real severity (a rare
admin-only path is Low; something in the hot per-agent-call path is High).

## PHASE 3 — Database Performance

- Identify any N+1 query pattern: look specifically at
  `list_tasks`/`list_epics`/`list_subtasks`/dashboard/metrics endpoints for
  missing `selectinload`/eager-loading where PROJECT.md documents this was
  a known past fix pattern (`selectinload for DevTask.repo everywhere`) —
  confirm it's still applied everywhere it's needed, including any NEW
  endpoint added since.
- Confirm the pgvector HNSW index actually exists per the migration DDL
  (cross-reference audit 06 if already run) and would be used by the
  similarity queries as written (correct column, correct operator).
- Confirm connection pooling settings (SQLAlchemy engine config) are
  reasonable for expected concurrency (not default-tiny, not unbounded).

## PHASE 4 — Token & Cost Controls

- Confirm `_trim_messages`'s context-window enforcement actually prevents
  unbounded message growth across long agent runs / long chat sessions —
  what's the actual trim strategy (drop oldest? summarize? hard cutoff?)
  and could it silently drop information the agent still needs?
- Confirm `budget_manager.check_run()`/`check_daily()` are actually called
  at real enforcement points (post-graph in `base_graph.py`) and that a
  `BudgetExceeded` exception genuinely halts further spend rather than just
  logging.
- Confirm `cost_controller.py`'s pre-flight estimate is used as an actual
  gate (interrupt before agents start over threshold) versus just being
  informational — trace the real call site.
- Assess whether per-agent model routing (`agent_models.json`) is
  cost-appropriate given the token budgets — cross-reference with audit 07
  if already run.

## PHASE 5 — Frontend Performance

- Check polling intervals across `apps/web/app/**/page.tsx` (task list,
  metrics, fleet dashboard, approvals) — are they reasonable (seconds, not
  sub-second aggressive polling that would hammer the backend under many
  concurrent users)?
- Confirm the SSE activity stream (`/api/tasks/{id}/stream`) has a sane
  heartbeat interval (per Day 18's fix, 15s) and won't accumulate unbounded
  server-side queue memory if a client disconnects without cleanup — check
  for connection-drop handling.
- Confirm large lists (task list, agent list, memory search results) are
  paginated or otherwise bounded, not rendering unbounded result sets.

## PHASE 6 — Scalability Assessment (static reasoning only)

- If this were deployed with 10 concurrent users each running epics, what's
  the first component likely to become a bottleneck based on the configured
  limits and connection pool sizes? Reason from the actual config values,
  not generic guesses.
- Is the worktree-per-task-per-epic disk usage pattern (git worktrees)
  bounded, or could disk usage grow unbounded without cleanup under
  sustained load? Check `remove_worktree()`'s cleanup triggers and whether
  any failure path skips cleanup.

## PHASE 7 — Final Report

1. Concurrency correctness findings
2. Blocking-call findings (file:line, severity)
3. Database performance findings
4. Token/cost control findings
5. Frontend performance findings
6. Scalability bottleneck reasoning (explicitly labeled as static analysis,
   not load-tested)
7. Prioritized fix list (Critical → Low, file:line)
8. Performance & Scalability Production-Readiness score (0-100)

Do not write code. Do not modify files. Evidence or NOT FOUND only. Clearly
distinguish "verified in code" findings from "reasoned/estimated" findings.
