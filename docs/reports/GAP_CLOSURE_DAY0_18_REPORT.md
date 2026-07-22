# Gap-Closure Report — Days 0-18 Full Re-Audit + Day 19 Production-Readiness Prep

**Date:** 2026-07-22
**Trigger:** User request, before Day 19: re-check the ENTIRE `docs/FLEET_ENHANCEMENT_PLAN.md`
(Days 0-18, not just recent days) for anything missing, and separately make the project
"production ready" for Day 19 while explicitly SKIPPING the actual deployment (no real
Vercel/Supabase/Railway accounts created).

This is the fourth gap-closure round this project has run (prior: Days 11-13, Days 11-15) and
the deepest — it covers the full history back to Day 0.

---

## Part 1 — Full Days 0-18 Re-Audit

### Method
Two parallel `Explore` agents audited (a) `model_router`/`budget_manager`/`tool_discovery` real
wiring and Day 0-6 flag/CONTRACT completeness, and (b) `capability_registry` completeness against
the Day 0 exit criteria and every fleet-event/trace_id call site. Findings were independently
confirmed by direct grep/read before any fix — the same discipline as every prior gap-closure
round.

### Confirmed clean (no action needed)
- `model_router` (`agent_models.json`): 72/72 real agents covered.
- `capability_registry` tag completeness: 72/72 agents, 0 duplicate capability tags.
- `VerificationConfig`: spot-checked 10 agents across different days, all non-empty
  `set_by`/`enforce_in_result` pairs (except legitimately tool-free `executive`/`manager`).
- `budget_manager`: has a real caller (`run_agent_graph()`'s post-graph section); enforcement is
  reactive (post-run), not pre-flight. Accepted as a legitimate design limit — LLM cost cannot be
  reliably predicted before a run completes — not force-fixed into a fake pre-flight estimate.
- `tool_discovery`'s `discover_tools()`/`check_compatibility()`/`register_tool()`: zero real
  callers beyond the one opt-in check already wired in the Days 11-13 gap-closure
  (`fleet_manager.select()`). Wiring `check_compatibility()` any further would only check a tool
  against the agent that already owns it — a trivially-true, meaningless check. Matches the
  established `prompt_registry.deploy()` precedent (Days 11-15 gap-closure): legitimately unused
  standalone infrastructure with no natural current consumer.

### Real gaps found and fixed

**1. A systemic `task_id` vs `trace_id` bug in `base_graph.py`'s `run_agent_graph()` (4 sites).**
`tid = trace_id or uuid.uuid4().hex[:12]` is a per-RUN correlation id, distinct from the real
`task_id` parameter. Four call sites used `tid` where the real `task_id` was needed:
`agent_registry.start_task(role_name, task_id=tid)`, and the `task_id=` field on the
`TaskStarted`, `TaskCompleted`, and `TaskFailed` fleet events. Since this code was written, every
one of these events and `agent_registry`'s `current_task_id` field has recorded a random trace
hex string instead of the real task id — breaking any downstream consumer that correlates events
by task (e.g. the Day 18 activity stream, `agent_registry.get_by_task()`-style lookups). Fixed all
4 sites; `trace_id=tid` usages were already correct and left untouched.

**2. Gap 7's exit criteria only half-satisfied: `HealthUpdated` missing on the error path.**
The success path published `HealthUpdated` after a run; the exception handler did not. Added a
`health_updated(role_name, health="error", state=str(exc)[:200], trace_id=tid)` publish in the
exception handler.

**3. `fleet_checkpoint.py`'s `save_checkpoint()`/`rollback_to()` had zero real callers anywhere** —
fully built and tested since Day 12, but the Failure Recovery Ladder's own Rollback/Resume rungs
had nothing real to act on. This is the 7th occurrence of the project's recurring "built but never
called" pattern. Wired `checkpoint()` into the two places the ladder already escalates from:
`base_graph.py`'s stall-path escalate block (checkpoints `final_state`) and its exception handler
(checkpoints `initial_state`), plus `manager.py`'s epic-abort block (checkpoints `results` +
`blocked_count`).

**4. Gap 10 (trace_id correlation) had several real call sites still hardcoding `trace_id=""`** —
`manager.py`'s `task_created` publish and its escalate/abort calls, and `api/agents.py`'s
blank-repo-bootstrap `task_started`/`task_completed` events and `record_approval()` call. Fixed
all with a consistent `f"task-{task_id}[-suffix]"` convention already used elsewhere in the
codebase (`thread_id=f"task-{task_id}"` for approval recording).

**5. Most of the 72 real agent modules were only ever imported lazily, on first dispatch** — before
this fix, `capability_registry` held as few as ~6 of 72 agents (only `pm`/`architect`/`decomposer`,
eagerly imported via `pipeline/graph.py`) for most of a fresh process's lifetime. This meant
`/health`'s agent count and any `fleet_manager.select()` call made shortly after startup — before
every agent type had been dispatched at least once — saw an incomplete registry. Added
`ensure_all_agents_registered()` to `capability_registry.py` (dynamic scan + import of every
`app/agents/*.py` module, idempotent, never raises on a single broken module), called once at
`main.py`'s `lifespan()` startup. Verified live: 72/72 agents registered immediately at startup.

### Testing
New `tests/test_gap_closure_days0_18.py` (8 tests): captures real `FleetEvent` objects (not just
"no exception raised") to assert `task_id`/`trace_id` fields directly; asserts a `HealthUpdated`
event fires on the exception path; asserts `fleet_checkpoint`'s `total_saved` counter increments on
both the exception path and the manager epic-abort path (using the real default
`manager_max_epic_failures=2` threshold — no settings mocking needed); asserts
`ensure_all_agents_registered()` imports ≥72 modules and `/health` reports `agents >= 72`.

Self-caused test pollution was found and fixed during this work: 3 of the new tests deliberately
force `role_name="pm"` to fail (to exercise the error path), which calls the real, process-wide
`agent_registry.fail_task("pm", ...)`. After 3+ failures `AgentInstance.fail()` marks health
`"unhealthy"`, which a plain `complete_task()` does not reset — breaking 2 previously-passing
tests in `test_session4_migration.py` (only when run after this file, confirmed by reproducing in
isolation vs. the full suite). Fixed with an `autouse=True` fixture that calls `.recover()` on
`"pm"` in teardown.

---

## Part 2 — Day 19 Production-Readiness Prep (deployment itself explicitly skipped)

Per the user's instruction, no Vercel/Supabase/Railway/Render account was touched and nothing was
deployed. What already existed was reviewed; what was missing or wrong was fixed.

### Already existed and required no changes
- `.github/workflows/ci.yml` — `backend` job (Postgres+pgvector service, Alembic migrations, ruff,
  black --check, `mypy app/ --strict`, `pytest tests/ -v`), `frontend` job (pnpm, typecheck,
  eslint, `next build`), `security` job (`pip-audit`). Deliberately no deploy job.
- `Procfile` — `web`/`worker` processes, already correct for Railway/Render.
- `apps/web/next.config.mjs` — backend URL already driven by `NEXT_PUBLIC_API_URL` with a sane
  local-dev fallback; no hardcoded production URL to fix.
- `/health` endpoint and the agent-count bootstrap (Part 1, finding #5) — now reports a real,
  complete agent count at startup, matching the plan's success criterion.

### Found and fixed
1. **`vercel.json` would have failed on a real Vercel build.** `installCommand`/`buildCommand` used
   `cd apps/web && npm ci` / `npm run build`, but `apps/web/` has no `package-lock.json` of its own
   — this is a pnpm workspace (root `pnpm-lock.yaml`, `packageManager: pnpm@11.9.0`), and `npm ci`
   requires a lockfile in the exact directory it runs in. Fixed to
   `pnpm install --frozen-lockfile` / `pnpm --filter @gridiron/web run build`, matching the CI
   workflow's own frontend job exactly.
2. **`backend/.env.example` was missing 18 of the 93 real `Settings` fields** (verified by diffing
   against `Settings.model_fields`, not by inspection alone): `OPENAI_API_KEY`, all 5 Groq
   variables, `AGENT_MODELS_PATH`, `MAX_TOKENS_OPUS`, `THINKING_BUDGET_OPUS`,
   `ALLOWED_WORKSPACE_PARENT`, `GIT_ALLOWED_HOSTS`, `SENTRY_DSN`/`SENTRY_ENVIRONMENT`/
   `SENTRY_TRACES_SAMPLE_RATE`, `ALERT_WEBHOOK_URL`/`ALERT_ON_BLOCKED`, `LOG_RETENTION_DAYS`,
   `DEFAULT_ADMIN_PASSWORD`. All added, grouped into their relevant existing sections. Backend
   `.env.example` now documents all 93 fields exactly (verified programmatically: 0 missing, 0
   extra).
3. **Root `.env.example` was stale TypeScript-era boilerplate** — it referenced "packages/
   shared-config (Zod schema...)" validation, which hasn't existed since the Python migration
   (CLAUDE.md: TS backend is archived in `TX/`), documented only 21 of 93 real backend variables,
   and included one stale variable (`CONTEXT_BUDGET_CHARS`, renamed to `CONTEXT_TOKEN_BUDGET` at
   some point without the root file being updated). Replaced with a short, accurate pointer to the
   two real env files.
4. **`apps/web/.env.example` did not exist.** Added (`NEXT_PUBLIC_API_URL`, matching the real
   `apps/web/.env.local` already in use for local dev).
5. **`docs/DEPLOYMENT.md` did not exist.** Added — a step-by-step guide for the user's own future
   deploy: Supabase + pgvector + migrations (with a documented asyncpg/pgbouncer pooler caution),
   Railway/Render backend env vars, Vercel frontend setup, the CI gate, the health check contract,
   and the manual production smoke test the plan calls for. Explicitly states nothing in it was
   executed this session.

### Testing
```
pytest tests/ -q
→ 2707 passed, 0 failed, 55 skipped, 17 deselected, 23 warnings in 93.70s

mypy app/ --strict
→ Success: no issues found in 173 source files

Frontend: pnpm --filter @gridiron/web run typecheck  → clean
          pnpm --filter @gridiron/web run lint        → 0 errors, 3 pre-existing unrelated warnings
          pnpm --filter @gridiron/web run build        → succeeds, 18/18 pages generated
```

### Verdict
✅ GREEN FLAG — GAP-CLOSURE (DAYS 0-18) + DAY 19 PRODUCTION-READINESS PREP COMPLETE.
Deployment itself intentionally not performed — see `docs/DEPLOYMENT.md` for the remaining manual
steps (Supabase/Railway/Render/Vercel account setup) required to go live.
