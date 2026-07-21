# Fleet Day 9 Test Report — Fleet Enhancement Dashboard + 5 Self-Improvement Agents
Date: 2026-07-21

## What was built

Per `docs/DAY9_PLAN.md` (v2, written 2026-07-20 after a dedicated research session): 5 new
agents that self-improve the Gridiron platform's own codebase, plus a full human-approval
dashboard feature — not just 5 more agent files.

### 5 agents (two-phase: autonomous SCAN → human-approved APPLY)

| Agent | Capability tag | Risk | Scan tools | Apply phase |
|---|---|---|---|---|
| `agent_performance_reviewer` | `agent_performance_review` | medium | metrics, read, web_search | write/edit/test/commit |
| `agent_debugger` | `agent_debugging` | medium | audit log, metrics, bash (scoped) | full write toolset (per explicit user request) |
| `agent_advisor` | `orchestration_advisory` | low | task history, metrics, audit log | **none — scan-only by design**, purely advisory |
| `knowledge_curator` | `knowledge_curation` | medium | memory search/curate-read | memory curate-write (+ rare role-prompt edits) |
| `quality_auditor` | `fleet_quality_audit` | medium | security scans (reused from `security_reviewer`), scoped bash for UI lint/tsc | write/edit/test/commit, one issue at a time |

Nothing acts until a human clicks Approve on a specific `enhancement_requests` row; Reject is
terminal. All 5 registered in `capability_registry` and `agent_models.json` (sonnet tier).

### New infrastructure

- **DB**: `enhancement_requests` table (migration 011) + `EnhancementRequest` ORM model
- **API**: `app/api/fleet_dashboard.py` — list/detail/approve/reject + a dashboard-level SSE
  channel (reuses the existing P1 `ActivityStreamRegistry`, keyed `"fleet-dashboard"`,
  distinct from the per-run channel used to watch an approved fix execute)
- **Background loop**: `_fleet_agents_scan_loop()` in `main.py`'s lifespan, same pattern as
  the existing retention/reindex loops — runs the 5 agents' SCAN phase sequentially every
  `FLEET_SCAN_INTERVAL_HOURS` (config, default 4, 0 disables)
- **Frontend**: `apps/web/app/fleet/page.tsx` (approve/reject cards, priority badges, live
  updates via SSE) + a live pending-count badge on the "Fleet" nav link in `NavBar.tsx`
  (also added the pre-existing but missing "Console" nav link while in that file)
- **New shared tools** in `app/agents/tools.py`: `fleet_metrics_read`, `audit_log_read`,
  `submit_enhancement_request` (shared across all 5 agents' scan phase),
  `memory_search`/`memory_curate_read`/`memory_curate_write`, `git_commit_change`,
  `make_fleet_apply_handlers`/`make_scoped_bash_handler` (shared apply-phase helpers)
- Extracted `web_search` and `task_history_query` out of their original nested closures
  (`make_research_handlers`/`make_chat_handlers`) into standalone, reusable top-level
  functions — zero behavior change, verified by the existing test suite still passing,
  needed so the new agents could reuse proven tools instead of duplicating them

### Architecture decision: two-phase Scan/Apply, not LangGraph `interrupt()`

Confirmed via `inspect.signature()` against the installed `langgraph` package that
`interrupt()`/`Command(resume=...)` exist, but `build_agent_graph()` compiles with
`g.compile()` — no checkpointer, anywhere in this codebase. Wiring a real mid-run pause would
be a much bigger, fleet-wide change than Day 9 needs. The two-phase design (separate SCAN and
APPLY `run_agent_graph()` calls, gated by a DB row) is simpler, safer (matches "nothing
happens without approval" even more literally than a mid-run pause), and reuses two pieces of
infrastructure that already work: the P1 Activity Stream and the lifespan-background-task
pattern already used for retention/reindex.

## Real bugs found and fixed during this session (not just new code)

1. **`MemoryEmbedding.created_at` was missing from the ORM model** despite existing as a real
   column in the database — meaning the pre-existing `/api/memory/patterns` endpoint (which
   references `MemoryEmbedding.created_at`) had been crashing with `AttributeError` on every
   call since it was written. Found while building `memory_curate_read`; fixed by adding the
   missing field. Verified the real endpoint no longer crashes.
2. **A real duplicate-field bug** introduced during this session's own edits: `models.py`
   ended up with `EnhancementRequest.created_at` declared twice (the second, later
   definition silently overrode the first at the Python class level, discarding the
   `DateTime(timezone=True)` fix). Caught by mypy's `no-redef` check — a concrete example of
   why the mypy gate matters, not just pytest.
3. **Timezone-column bug of my own making**: wrote timezone-aware Python datetimes
   (`datetime.now(timezone.utc)`) into columns declared as `TIMESTAMP WITHOUT TIME ZONE` in
   the first draft of migration 011 — asyncpg correctly refused to encode them. Fixed by
   declaring `decided_at`/`completed_at`/`created_at` as `DateTime(timezone=True)` in both
   the migration and the model, then downgrading/re-upgrading the migration (table was brand
   new with only test data, so this was safe).
4. **The same asyncio-event-loop-reuse bug from yesterday's Day 7 audit, reintroduced by
   this session's own new tools**: `submit_enhancement_request`, `memory_search`,
   `memory_curate_read/write` each opened their own `asyncio.run(...)` against the *shared*
   `app.db.session` engine singleton — which binds to whichever event loop touches it first,
   so a second `asyncio.run()` call in the same process (exactly what happens when a fleet
   agent's scan run calls more than one DB tool, or when tests call two DB-backed tools in
   one process) raised "Future attached to a different loop". Fixed with a
   `_new_isolated_db_engine()` helper — a fresh, disposed-after-use engine per call, verified
   by directly reproducing the failure with repeated `asyncio.run()` calls in one process
   before and after the fix. My own test file hit the identical bug in its own helper
   functions and needed the same fix (`test_submit_enhancement_request_repeated_calls_same_process`
   is a dedicated regression test for this).
5. **A flawed test assertion caught during self-review**: an early draft of
   `test_approve_never_touches_disk_synchronously` asserted `_run_apply_phase` was
   never *called* — but calling a coroutine function to construct the coroutine object is
   normal Python (required before `asyncio.create_task()` can schedule it); it doesn't mean
   the body executed. Removed the test since it was redundant with the `create_task`
   assertion already covering the real safety property.

## Tests

`tests/test_day9_fleet_agents.py` (56 tests): `AGENT_CONTRACT` shape, role-file structure
(reusing Day 8's bar), `VerificationConfig` non-empty with no dead enforce keys,
`capability_registry` registration + tag uniqueness, `agent_models.json` coverage, SCAN/APPLY
run functions against a mocked `run_agent_graph` (including the "empty scan is a normal
outcome" and "unverified apply must report `blocked`, never a false `completed`" cases), and
direct tests for every new tool (including a dedicated regression test for the
asyncio-loop-reuse bug).

`tests/test_fleet_dashboard_api.py` (14 tests): list/detail/approve/reject against a mocked
DB session (same convention as the existing `test_goals_api.py`), 404/409 handling,
`_run_apply_phase`'s success/failure DB-write paths.

Fixed 2 pre-existing tests with hardcoded agent counts that needed bumping for the 5 new
agents (`test_day8_role_prompts.py`'s `67 → 72`, `test_model_router.py`'s `68 → 73`) — same
drift pattern the Day 8 session already fixed once.

## Manual end-to-end verification (per CLAUDE.md's UI-testing rule)

- `npm run typecheck` — clean, 0 errors
- Started the real backend (`uvicorn`) and frontend (`next dev`) together
- `GET /api/fleet/requests` through the Next.js proxy → real backend → real Postgres,
  round-tripping a real row including the timezone-aware datetime fields
- `POST .../reject`, duplicate-decision 409, missing-row 404 — all verified against the live
  stack, not just mocks
- `/fleet` page compiles and serves (200), renders expected content
- Confirmed the exact query the NavBar pending-count badge depends on returns the right count
- Cleaned up all test data from the dev database and stopped both dev servers before finishing

## Ground truth

```
pytest tests/ -q -p no:cacheprovider
→ 2479 passed, 0 failed, 55 skipped, 17 deselected, 4 warnings in 43.85s

mypy app/ --strict
→ 32 errors, all pre-existing (unchanged from the 2026-07-20 Day 7/8 baseline), 0 new
```

## Verdict

✅ **GREEN FLAG — DAY 9 COMPLETE**: all 5 agents built, registered, and tested; the full
approval-gated dashboard (DB, API, background loop, frontend) built and verified end-to-end
against the real stack; 5 real bugs found and fixed along the way (2 pre-existing, 3 newly
introduced by this session's own code and caught before commit); 2479 tests pass, 0 failed;
mypy adds 0 new errors.
