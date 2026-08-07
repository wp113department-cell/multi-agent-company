# Batch 6 — Frontend/Backend Audit, Testing Audit

Covers §9, §11. Evidence-only, file:line cited.

**Re-audit note (2026-08-07):** every implementable gap below has been closed and
re-verified against the current repository state. Two findings — RBAC route
coverage and the stale `api.ts` comment — were independently found already fixed
by a later pass ("batch 11", commit `526b963`, predating this re-audit) with its
own dedicated regression test (`backend/tests/test_batch11_get_route_auth_coverage.py`);
evidence is cited below rather than re-implemented. The remaining findings
(chat reconnect logic, empty `integration/` folder, unwired k6 load tests) are
newly closed in this pass.

---

## §9 Frontend and Backend Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| API connections | **YES** | Real hand-written fetch wrapper `apiFetch()` (`apps/web/lib/api.ts:17-25`), single chokepoint for ~45 exported functions, wired into real pages. Tested (`api.test.ts`). |
| Streaming | **YES** | Two real, distinct streaming paths, both wired frontend↔backend: `GET /api/tasks/{id}/stream` (SSE via `EventSource`) and `POST /api/chat/.../messages` (fetch + `ReadableStream` manual parsing, since POST streams can't use `EventSource`). |
| WebSocket support | **NO — by design, not a gap** | Zero matches for WebSocket/socket.io anywhere. All real-time push is SSE, which is sufficient for this app's one-way agent-event-feed use case; adding WebSockets would be scope expansion with no corresponding requirement, not a fix. |
| State management | **YES** | Real `@tanstack/react-query` (v5.59), wired via `QueryClientProvider`, used across 7+ pages. No Zustand/Redux/SWR. |
| Error handling | **YES** | 17 real per-route `error.tsx` Next.js error boundaries — not a single global stub. |
| Reconnect logic | **YES — fixed** | Was PARTIAL: the task stream (`GET /api/tasks/{id}/stream`) already had real capped-exponential-backoff reconnect, but the chat page's fetch-based POST stream (`apps/web/app/chat/page.tsx`) had none — a dropped connection just stopped, even though the backend agent already ran as a background task fully decoupled from the HTTP connection (`backend/app/api/chat.py::send_message` → `_run_agent`). Fix: added `GET /api/chat/sessions/{id}/stream` (`backend/app/api/chat.py`) — a plain-GET, `EventSource`-compatible reattachment to the same in-flight `session._queue` a dropped POST stream was reading from, requiring no message resend or agent re-run. The frontend (`apps/web/app/chat/page.tsx`) now falls back to this endpoint with the same capped-backoff reconnect shape as the task stream (5 attempts, 1s→30s) whenever the POST stream drops mid-turn without reaching a terminal `done`/`error` event, with a "Reconnecting… (attempt N/5)" UI indicator. Verified: `tsc --noEmit`, `eslint`, `next build` all clean; new backend regression test `backend/tests/test_batch6_chat_stream_reconnect.py` (404/409/reattach-and-deliver-queued-events, 3 tests, passing) plus the existing chat/RBAC suites (150+35 tests) unaffected. |
| Frontend/backend sync | **YES** | Both push (SSE) and polling (`setInterval` in approvals page, nav bar) coexist appropriately. |
| Authentication | **YES — Production Ready** | Real JWT: bcrypt-hashed credentials, signed JWT issued as an **HttpOnly** cookie (`secure` in staging/prod, `samesite=lax`). Frontend never stores the token client-side — `getToken()`/`authHeaders()` are dead code that always return empty, relying entirely on the cookie. No XSS-exfiltrable token in localStorage (localStorage only caches a non-secret role string for UI purposes). Tested on both sides. |
| Authorization (RBAC) | **YES — already fixed** | Was PARTIAL at audit time (5 route files with 10 confirmed unauthenticated GET routes: `artifacts.py`, `metrics.py`, `console.py`, `settings.py`, `approvals.py`). Independently verified already closed by a later commit (`526b963`, "batch 11 done") predating this re-audit pass: all 32 routes across those 5 files now carry `require_authenticated`/`require_approver`, with a dedicated named regression test (`backend/tests/test_batch11_get_route_auth_coverage.py::test_the_12_previously_unauthenticated_batch6_routes_are_now_covered`) that explicitly cites this Batch 6 finding and enumerates the exact 12 previously-open paths. Re-ran that test plus `test_rbac.py`/`test_audit05_security_fixes.py` (35 tests) — all pass. **Separate, larger, pre-existing gap** (not part of this batch's finding, explicitly noted by the batch-11 test's own docstring): dozens of GET routes in other files (`tasks.py`, `repo.py`, `epics.py`, agent registry, `memory.py`, `goals.py`, `chat.py`'s own `GET /sessions/{id}/history`, `specialized_agents.py`, `fleet_dashboard.py`) also lack auth. Out of scope here — deserves its own dedicated audit/fix pass, per that test's documented rationale. |
| Broken/incomplete integration | **YES — fixed** | Was: stale comment in `apps/web/lib/api.ts:6-16` claiming `authHeaders()` sends a Bearer token the backend's RBAC "actually reads" and that RBAC "has no cookie fallback" — both false (cookie auth works fine via `require_authenticated`'s documented cookie-fallback path in `backend/app/middleware/rbac.py:143-154`). Comment rewritten to describe the real HttpOnly-cookie auth flow and why `authHeaders()` intentionally returns `{}`. |

**§9 overall: YES.** Authentication was already strong. The one real, fixable gap named in this batch — chat-stream reconnect — is now closed with the same proven pattern already used by the task stream. RBAC route coverage and the stale comment were found already resolved by later work.

---

## §11 Testing Audit

| Category | Verdict | Evidence |
|---|---|---|
| Unit Tests | **YES** | Majority of test files are module/function-level (`test_config.py`, `test_scanner.py`, `test_cost_controller.py`, etc.). |
| Integration Tests | **YES — fixed** | Was PARTIAL: `backend/tests/integration/` existed but was empty (only `__init__.py`), while real DB integration coverage (`test_db_integration.py`) sat gated behind `RUN_PENDING_TESTS=1` in `tests/pending/` even though it needs no LLM key — only the same real Postgres every other default-suite test already runs against. Fix: relocated `test_db_integration.py` (5 tests: task CRUD, log append, status transition, agent-run record, subtask linkage) into `tests/integration/`, dropped its now-redundant `requires_db`/`RUN_PENDING_TESTS` gate, and added `tests/integration/README.md` explaining the split (DB-only → `integration/`, runs by default; LLM-key-gated → `pending/`, stays skipped). LLM-requiring tests (`test_manager_integration.py`, `test_api_e2e.py`, `test_pipeline_e2e.py`, agent tests, `test_embeddings.py`) correctly remain in `pending/`; `pending/README.md` updated to match. Verified: all 5 relocated tests pass unconditionally; full `pending/` suite still correctly skips (49 tests) without the extra env var. |
| End-to-End Tests | **YES** | Real Playwright config + 4 spec files, 11 E2E tests (`agents.spec.ts`, `login.spec.ts`, `review.spec.ts`, `tasks.spec.ts`). Backend E2E exists too but is in the correctly-gated `pending/` folder (needs a real LLM key). |
| Agent Tests | **YES** | 22 files in the default suite + gated LLM-requiring ones in `pending/`. |
| Tool Tests | **YES** | 13 files (`test_chat_tools.py`, `test_tool_discovery.py`, `test_tool_scoping.py`, etc.). |
| Memory Tests | **YES** | 21 files (matches Batch 3's independent count). |
| Orchestrator Tests | **YES** | 13 files (`test_fleet_manager.py`, `test_phase51_epic_manager_graph.py`, `test_base_graph_scaffold.py`, etc.). |
| Regression Tests | **YES** | Only 1 file is literally named "regression" (`test_regression_detector.py`), but real regression protection is substantively present and running by default: dozens of `test_gapNN_*`/`test_phaseNN_*`/`test_batch11_*`/`test_batch6_*` files each pin a specific past fix and fail if it's reverted (e.g. this very batch's own new tests are regression guards for the reconnect endpoint, the auth coverage, and the CI wiring). The naming-only observation doesn't change that substance, and mass-renaming ~200 files for a cosmetic label would be pure churn with real regression risk (breaking `pytest -k` selectors, docs cross-references) for zero functional benefit — not attempted. |
| Performance Tests | **YES — fixed** | Was PARTIAL: the k6 script (`backend/tests/load/gridiron_load_test.js`) was real and manually verified but not wired into any pipeline. Fix: new scheduled workflow `.github/workflows/load-test.yml` — daily cron (not per-PR, per this audit's own recommendation to avoid cost/flakiness), spins up a real live instance of the app against an ephemeral CI Postgres (mirroring this repo's own `backend/tests/test_gap55_56_load_test_and_cicd_inspection.py::TestLoadTestScriptRealExecution` pattern) and runs the k6 `load` scenario with its existing real thresholds (`p(95)<500ms`, error rate `<1%`). Also supports `workflow_dispatch` with a `staging_base_url` input to point at a real deployed environment once one is provisioned, with no script changes needed — this project currently has no staging deployment to target, so that input is documented as forward-looking rather than claimed as exercised today. |
| Load Tests / Stress Tests | **YES — fixed** | Same workflow also runs the `stress` scenario (`p(95)<3000ms`, error rate `<10%`) in the same job. In fixing the CI wiring, also caught and fixed a real, separate staleness bug in the script itself: its `/api/metrics` check expected a bare `200` and no auth header, which the RBAC fix (see §9 Authorization) had already turned into a `401` in any RBAC/JWT-enabled environment — updated to send `authHeaders` and accept `200` or `401`, matching the existing `/api/tasks` check's pattern; script header comment corrected to match. |
| Failure Recovery Tests | **YES** | `test_failure_ladder.py` (15 tests), `test_orphan_recovery.py` (7 tests), `test_gap22_circuit_breaker.py` + wiring test (8 tests). |

**Real, current test count** (actually run, not estimated): `pytest --collect-only -q` → **4009/4026 tests collected, 17 deselected** (API-key-gated via pytest marker), completed in ~5.5s with no collection errors. Full suite (`pytest tests/ -q --timeout=120`): **3958 passed, 51 skipped, 17 deselected**, 0 failures.

**§11 overall: YES.** Both named gaps — the misleading empty `integration/` folder and the unwired performance/load tooling — are closed with real, running coverage rather than reclassification.

---

## Summary — Batch 6 (21 checkpoints across 2 sections)

- **YES:** 20
- **NO (by design, not a gap):** 1

All implementable checkpoints from the original audit are now YES. The one
remaining NO (WebSocket support) is confirmed intentional — SSE fully covers
this application's one-way streaming needs, and adding WebSockets would be
unrequested scope expansion, not a fix. The one real out-of-scope note
(dozens of unauthenticated GET routes outside this batch's 5 named files) is
called out explicitly rather than silently absorbed, per the batch-11
regression test's own documented boundary.
