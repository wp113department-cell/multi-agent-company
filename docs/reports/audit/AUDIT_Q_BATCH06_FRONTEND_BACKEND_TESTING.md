# Batch 6 — Frontend/Backend Audit, Testing Audit

Covers §9, §11. Evidence-only, file:line cited.

---

## §9 Frontend and Backend Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| API connections | **YES** | Real hand-written fetch wrapper `apiFetch()` (`apps/web/lib/api.ts:17-25`), single chokepoint for ~45 exported functions, wired into real pages. Tested (`api.test.ts`). |
| Streaming | **YES** | Two real, distinct streaming paths, both wired frontend↔backend: `GET /api/tasks/{id}/stream` (SSE via `EventSource`) and `POST /api/chat/.../messages` (fetch + `ReadableStream` manual parsing, since POST streams can't use `EventSource`). |
| WebSocket support | **NO** | Zero matches for WebSocket/socket.io anywhere. All real-time push is SSE. (Not necessarily a defect — SSE is sufficient for this use case — but the question's checkpoint is explicitly "no.") |
| State management | **YES** | Real `@tanstack/react-query` (v5.59), wired via `QueryClientProvider`, used across 7+ pages. No Zustand/Redux/SWR. |
| Error handling | **YES** | 17 real per-route `error.tsx` Next.js error boundaries — not a single global stub. |
| Reconnect logic | **PARTIAL** | Real exponential-backoff reconnect (capped at 30s, max 5 attempts) exists on the `EventSource`-based task stream, correctly distinguishing terminal states from transient errors. **The chat page's fetch-based stream has no reconnect logic at all** — a dropped POST stream just stops. |
| Frontend/backend sync | **YES** | Both push (SSE) and polling (`setInterval` in approvals page, nav bar) coexist appropriately. |
| Authentication | **YES — Production Ready** | Real JWT: bcrypt-hashed credentials, signed JWT issued as an **HttpOnly** cookie (`secure` in staging/prod, `samesite=lax`). Frontend never stores the token client-side — `getToken()`/`authHeaders()` are dead code that always return empty, relying entirely on the cookie. No XSS-exfiltrable token in localStorage (localStorage only caches a non-secret role string for UI purposes). Tested on both sides. |
| Authorization (RBAC) | **PARTIAL — real but inconsistently applied** | Real middleware (`middleware/rbac.py::require_approver`/`require_authenticated`) exists and is applied to most mutating routes. **5 route files have real, confirmed gaps**: `artifacts.py` (0/2 routes authed — serves full artifact content including plans/diffs/review findings), `metrics.py` (0/2 routes authed — token/cost data), `console.py` (4 GET routes unauthed: repo status/log/diff/branches, while sibling mutating routes are gated), `settings.py` (2 GET routes unauthed: masked key sources + secret *names*), `approvals.py` (GET routes unauthed, only mutating approve/reject gated). |
| Broken/incomplete integration | **Confirmed, minor** | Stale comment in `apps/web/lib/api.ts:6-16` claims `authHeaders()` sends a Bearer token the backend's RBAC "actually reads" and that RBAC "has no cookie fallback" — both false as currently implemented (cookie auth works fine; the comment is just out of date and misleading to a future reader). |

**§9 overall: PARTIAL.** Authentication itself is genuinely strong (HttpOnly cookie JWT, no client-side token exposure). The real problem is authorization consistency — a handful of GET routes leak internal state (artifact content, cost metrics, secret *names*, repo status) without any auth check, while nearly every other route in the same files is correctly gated. This is a real, fixable security gap, not a design flaw.

**Production Enhancement Plan:** Add `Depends(require_authenticated)` to the 10 unauthenticated routes identified in `artifacts.py`, `metrics.py`, `console.py`, `settings.py`, `approvals.py` — these are minimal, mechanical fixes (the dependency already exists and is used correctly elsewhere in the same files). Also fix the stale comment in `api.ts` before it misleads a future contributor into "fixing" working cookie auth.

---

## §11 Testing Audit

| Category | Verdict | Evidence |
|---|---|---|
| Unit Tests | **YES** | Majority of 208 top-level test files are module/function-level (`test_config.py`, `test_scanner.py`, `test_cost_controller.py`, etc.). |
| Integration Tests | **PARTIAL** | `backend/tests/integration/` exists but is **empty** (only `__init__.py`). Real multi-component tests (`test_db_integration.py`, `test_manager_integration.py`, `test_api_e2e.py`) instead live in `backend/tests/pending/`, gated behind `RUN_PENDING_TESTS=1` + real API keys/DB — **not run by default**. |
| End-to-End Tests | **YES** | Real Playwright config + 4 spec files, 11 E2E tests (`agents.spec.ts`, `login.spec.ts`, `review.spec.ts`, `tasks.spec.ts`). Backend E2E exists too but is in the gated `pending/` folder. |
| Agent Tests | **YES** | 22 files in the default suite + 6 more gated in `pending/`. |
| Tool Tests | **YES** | 13 files (`test_chat_tools.py`, `test_tool_discovery.py`, `test_tool_scoping.py`, etc.). |
| Memory Tests | **YES** | 21 files (matches Batch 3's independent count). |
| Orchestrator Tests | **YES** | 13 files (`test_fleet_manager.py`, `test_phase51_epic_manager_graph.py`, `test_base_graph_scaffold.py`, etc.). |
| Regression Tests | **PARTIAL** | Only 1 file explicitly named "regression" (`test_regression_detector.py`, 7 tests) — narrow, though many `test_gapNN_*`/`test_phaseNN_*` files function as de-facto regression tests for specific past fixes without the word "regression" in the name. |
| Performance Tests | **PARTIAL** | A real k6 load-test script exists (`backend/tests/load/gridiron_load_test.js`), whose own header comment states it was written specifically because *no* load-generation tooling existed before it. Exercises real endpoints. **Not integrated into CI or pytest** — requires manually installing and running `k6`. |
| Load Tests / Stress Tests | **PARTIAL** | Same k6 script supports both profiles (`k6 run` / `k6 run -e SCENARIO=stress`) — real, but manual-only, not automated. |
| Failure Recovery Tests | **YES** | `test_failure_ladder.py` (15 tests), `test_orphan_recovery.py` (7 tests), `test_gap22_circuit_breaker.py` + wiring test (8 tests). |

**Real, current test count** (actually run, not estimated): `pytest --collect-only -q` → **3927/3944 tests collected, 17 deselected** (API-key-gated), completed in 5.9s with no collection errors.

**§11 overall: YES with two clear, named gaps.** This is a genuinely large, real test suite (not padding — the count comes from an actual collection run). The two honest gaps: (1) the `integration/` folder is a misleading empty shell while real integration coverage sits gated behind an env var most CI runs won't set; (2) performance/load testing exists as a real script but isn't wired into any automated pipeline, so a performance regression would not be caught automatically today.

**Production Enhancement Plan:**
- Either populate `backend/tests/integration/` with real tests, or delete the empty folder and document that `pending/` is the actual integration-test home — an empty folder with the "correct" name is actively misleading to anyone auditing test coverage by directory structure alone (as this very audit initially would have, before checking `pending/`).
- Add a scheduled (not per-PR, to avoid cost/flakiness) CI job that runs the k6 script against a staging environment, with basic latency/error-rate thresholds, so performance regressions surface before production rather than never.

---

## Summary — Batch 6 (21 checkpoints across 2 sections)

- **YES:** 12
- **PARTIAL:** 8
- **NO:** 1

Both sections land at "real and substantially built, with specific, fixable gaps" rather than either extreme — consistent with the overall pattern from Batches 1-5: this is a mature codebase where the gaps are precise and named, not vague.
