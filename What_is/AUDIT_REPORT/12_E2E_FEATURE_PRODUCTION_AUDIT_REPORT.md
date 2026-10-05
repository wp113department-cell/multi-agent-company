# Audit 12: End-to-End Feature Production

**Spec:** `files/Audit/12_MASTER_END_TO_END_FEATURE_PRODUCTION_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-10-02 · **JSON sidecar:** `json/AUDIT_12_E2E_FEATURE_PRODUCTION.json`
**Evidence:** `evidence/api_wiring.py`, `evidence/shadowed_routes.py` (+ `.out.json`), real-stack spec `apps/web/e2e-real/journeys.spec.ts`

## Result

🟡 **YELLOW: every feature that works without a paid LLM call is now proven on the real stack (real browser → production Next build → real FastAPI → real Postgres, nothing mocked). Doing that found 5 real bugs that all mocked tests had hidden, all fixed. The 3 LLM journeys (plan approval, agent execution, repository chat) are BLOCKED until the live run (`PENDING_TESTS_API_KEYS.md` L8–L10).**

**Score: 80 / 100.**

## Why the real stack mattered

Every existing e2e test **mocks the backend** (`page.route()`): the test answers its own requests. Run against the real backend for the first time, three user-facing features turned out to have **never worked**:

| ID | Sev | Feature | What really happened | Fix |
|---|---|---|---|---|
| E2E-12-001 | **High** | **Daily Review page** (`/review`) | `GET /api/epics/batch-review` → **500**. `GET /api/epics/{epic_id}` was declared first, so "batch-review" was parsed as an epic UUID. The page could never load its data. | Route moved above `/{epic_id}` (`api/epics.py`) |
| E2E-12-002 | **High** | **Daily Review page**, once anything is waiting | `TypeError: can't subtract offset-naive and offset-aware datetimes`: `datetime.utcnow() - created_at` → 500 as soon as one epic or task is ready for review. Hidden behind 001. | `datetime.now(timezone.utc)` |
| E2E-12-003 | **High** | **Logout** | **Every logout was a 500** and the httpOnly session cookie was **never cleared**. The handler returned FastAPI's injected `Response` (status `None`), which uvicorn can't send. The UI clears its local state, so it looked fine; the session cookie stayed valid in the browser. | Return a real `Response(204)` that deletes the cookie (`api/auth.py`) |
| E2E-12-004 | Medium | **NavBar live updates** (every page) | `GET /api/fleet/requests/stream` was shadowed by `/requests/{request_id}`, so the live stream never connected (NavBar swallows the error). Badges updated only by polling. | Route moved above `/{request_id}` (`api/fleet_dashboard.py`) |
| E2E-12-005 | Medium | Epic API input | A non-UUID epic id reached the database → **500** instead of a validation error | `EpicId` path type validates UUID → 422 |
| E2E-12-006 | Low | Create task API | A whitespace-only title was stored (201); only the UI blocked it | Validator strips and rejects blank → 422 |

A new scan (`evidence/shadowed_routes.py`) checks **every router** for routes hidden behind an earlier path parameter. Before: 2. After: **0**, and a test keeps it at 0.

## Wiring (frontend ↔ backend)

`evidence/api_wiring.py` compares every `/api/...` path the frontend calls with the backend's real route table:

| Check | Result |
|---|---|
| Frontend API call sites | 81 (+ 11 console calls built from `${API}`) |
| **Frontend calls with no backend route** | **0.** The 5 raw hits were all script artifacts (query strings, `${action}` approve/reject, `${API}` base), each checked by hand against the route table |
| Backend `/api` routes the UI never calls | 69: agent-to-agent, admin, webhook, metrics and test-support endpoints. Not a defect; the API is wider than the UI. |
| Routes unreachable because of shadowing | 2 → **0** |

## Real-stack journeys (no mocks), all passing

Run: backend `uvicorn` on :8000 with a **fake Anthropic key and blank Voyage key** (so no paid call can happen), frontend `next build` + `next start` on :3100, Chromium. Throwaway users `audit12` (approver) and `audit12viewer`, deleted afterwards.

| Journey | Proof | Result |
|---|---|---|
| A1 wrong password | real 401, stays on `/login`, error shown | ✅ |
| A2 login | real JWT session, cookie is **httpOnly** | ✅ |
| A3 API without session | `GET /api/tasks` → 401 | ✅ |
| B create task | typed in the UI → `POST /api/tasks` 201 → read back via the real API → visible in the list and on its detail page | ✅ |
| Page tour (16 pages) | `/repo /tasks /approvals /review /fleet /agents /metrics /cost /settings /epics /goals /roadmap /stream /chat /console /onboarding`: no 5xx, no error screen, no bounce to login; **0 server errors in the backend log, and the only 4xx were the two intended 401s** | ✅ (was ❌: `/review`) |
| A4 logout | 204, cookie cleared, protected page → `/login` | ✅ (was ❌: 500) |
| F terminal | real Docker PTY over WebSocket: `tests/test_terminal_websocket.py` (7/7, real containers, audit 09) | ✅ backend-level |
| C plan approval · D agent execution · G repo chat | need real LLM calls | ⛔ **BLOCKED** → `PENDING_TESTS_API_KEYS.md` L8–L10 (same harness) |
| E failure recovery · H fleet enhancement | covered at service level in audits 04/07 | backend-level only |

Mocked suite (`pnpm test:e2e`): **11/11** still pass.

## Negative testing (real backend)

| Input | Result |
|---|---|
| empty body / malformed JSON | 422 with clear field errors |
| task id not a number · missing task | 422 · 404 |
| **non-UUID epic id** | ~~500~~ → **422** (fixed) |
| **whitespace-only title** | ~~201~~ → **422** (fixed) |
| viewer creates a task / approves | 403 "approver required" |
| forged JWT cookie | 401 "Invalid token" |
| 12 wrong logins in a row | 8 × 401, then **429** (rate limit works) |

Error envelope is consistent: `{"error":{"code","message"}}`.

## Tests added

- `backend/tests/test_audit12_route_reachability.py`: no route shadowed anywhere; batch-review with **real** waiting epic and task rows returns 200 with ages; logout returns 204 and clears the cookie (**fails on the old code**); bad epic id and blank title are 422, not 500.
- `apps/web/e2e-real/journeys.spec.ts` + `playwright.real.config.ts`: the real-stack journeys, reusable for L8–L10.
- Regression: epics/tasks 201 passed; auth/RBAC/JWT/fleet-dashboard 178 passed; epic/review/fleet/stream 699 passed (the one failure, an audit-log chain test, came from the live backend writing to the same chain at the same time; it passes alone, 5/5).

## What's still needed for GREEN

Run L8–L10 in the live LLM session (Haiku, economy, throwaway repo, under the $3.50 stop).

## Update 2026-10-05: GREEN (live LLM journeys)

`apps/web/e2e-real/live-ai.spec.ts` (off unless `LIVE_AI=1`) ran on the real stack: production Next build → FastAPI → isolated Postgres → real Haiku, economy mode, throwaway git repo, spend cap. A $0 rehearsal with a fake key ran first.

| Journey | Result |
|---|---|
| **C** (L8) Smart Run → routed plan waits for approval → approve → coding starts | ✅ |
| **D** (L9) backend_dev codes in a worktree → committed diff on the task page → Approve & Complete | ✅ |
| **G** (L10) repository chat answers about the repo (names both real functions) | ✅ |

**Real bugs found, all fixed with tests:**

| Bug | Effect |
|---|---|
| "Approve Plan & Start Coding" on the task page called `POST /run`, which refuses `ready_for_review` (since 2026-07-02) | A Smart Run or quick plan could never be approved from the UI |
| `git_add`/`git_commit` in the task worktree failed the `/home` workspace guard (worktrees live in `/tmp/gridiron-worktrees`) | Every coding task that changed files ended **blocked** |
| Chat on Sonnet in every mode, no caching, condensing every turn | $0.72 per question → $0.047 |

Notes:
- The Review page lists plans and epics awaiting approval; finished diffs are reviewed on the task page (by design).
- A git-push approval is only recorded for GitHub-cloned repos. The throwaway repo has no remote, so tests never push.

E2E-12-007 is **CLOSED**. Score: **80 → 90 / 100**.
