# 12 — End-to-End Feature Reality / Feature Production Audit

**Audit date:** 2026-10-02
**Repository:** /home/pc-117/Documents/CRR2906 — "Gridiron Developer Department"
**Commit:** 90dac23bad223ec39413c485d1ddb68f9646975e ("Production audit 14: clean-room reproduction from README; fix onboarding blockers")
**Series baseline:** c927c44b ("Production audits 09 and 11"); audits 01–11 of this series were run against disk state 33bbd03c. This audit reads the current tree, which additionally includes commits ecd4905a ("Production audit 12"), 33bbd03c ("Production audit 13"), 90dac23b ("Production audit 14") made by a parallel repair pass; those commits are the **object under audit**, not proof of correctness.
**Worktree:** clean; untracked only: `files/Qoder_audit report/`, `files/Antigravity_audit_report/`, `What_is/AUDIT_REPORT/NEXT_PLAN_MONDAY.md`.
**Environment:** Linux 24.04; Python 3.12 venv; Next.js production server currently UP on :3100 (HTTP 200 `/login`); backend :8000 **DOWN**; Postgres :5432 and Redis :6379 listening; no real ANTHROPIC/OPENAI keys configured (`PENDING_TESTS_API_KEYS.md`).

## 0. Method and overriding constraint

The audit brief mandates repair-and-retest (§6, §46–69). The governing user instruction for this engagement is **strict read-only**: no project code may be modified; the only writable outputs are the numbered report files in `files/Qoder_audit report/` and their `json/` sidecars. Therefore **no repairs were performed**, and every verification step that requires a running backend, a browser/Playwright execution, real LLM keys, or write access to infrastructure is reported as **UNVERIFIED** — never as PASS (§3: missing evidence ⇒ UNKNOWN/UNVERIFIED).

Evidence rules applied: only real call sites, route registrations, frontend client code, and command output count as proof (§2.1). Comments, docstrings, README claims, route declarations alone, and prior audit claims are treated as leads, not proof (§2.2). Findings below were verified by reading the actual files at the exact line numbers cited.

## 1. Final Decision

**NOT GREEN — PRODUCTION FEATURE AUDIT INCOMPLETE**

Rationale (honest, per §101):
- **Zero Critical findings** (no authentication bypass, no data-loss path, no security hole, no broken core wiring).
- **2 feature paths are BROKEN** and **1 advertised capability is UNWIRED** (below).
- **All runtime gates are UNVERIFIED** in this read-only engagement (backend down, no LLM keys, no E2E credentials). Gate F (Runtime Integration) and the LLM-dependent portions of Gate G (Tests) cannot be executed; §101 requires "Every required feature verified" — it is not.
- The already-committed real-stack Playwright suite (`apps/web/e2e-real/journeys.spec.ts`, added by ecd4905a) is the strongest runtime artifact in the tree, but it was **not executed during this audit** (backend :8000 was down, and journeys C–H require paid LLM calls by design).

Feature counts: see §7. No green may be claimed while runtime verification is incomplete and two feature paths are broken, regardless of the high static-wiring coverage.

## 2. Feature Inventory and Master Matrix (static evidence at 90dac23b)

| ID | Feature | UI | API | Service | DB | External | E2E artifact | Security | Status |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | Auth: login / logout / setup (Journey A) | PASS (login page; middleware) | PASS (auth.py:66,205,166) | PASS (jwt/session) | PASS (users) | N/A | PASS (A1–A4 spec committed) | PASS (HttpOnly cookie; 401 tests) | VERIFIED (static) |
| F-02 | Auth extras: refresh / me / change-password | — (no UI) | PASS (auth.py:121,131,219) | PASS | PASS | N/A | — | PASS | VERIFIED (static, API-only) |
| F-03 | Task intake & CRUD (create/edit/priority/logs/images/PDF) | PASS (tasks, tasks/[id], NewTaskForm) | PASS (tasks.py:171,203,218,231,247,307,318,1134,1216–1322) | PASS | PASS | N/A | partial (B covers create) | PASS (auth dep) | VERIFIED (static) |
| F-04 | Task execution: run / restart / repeat | PARTIAL (run via review/approval flows) | PASS (tasks.py:329,444,611) | PASS (orchestrator) | PASS | LLM (UNVERIFIED) | LLM-gated | PASS | VERIFIED (static; runtime LLM-gated) |
| F-05 | Plan/task decisions: pipeline approve/reject + approvals + review pages | PASS (approvals, review, tasks/[id]) | PASS (tasks.py:762,827; approvals.py:63–277) | PASS (approval_gate async) | PASS | N/A | LLM-gated (needs plan) | PASS (require_daily_budget) | VERIFIED (static) |
| F-06 | Task SSE stream + stop + resume | PASS (stream/[taskId]) | PASS (activity.py:48,86,101) | PASS | PASS | N/A | spec exists (not run) | PASS | VERIFIED (static) |
| F-07 | Task cancel + token usage (backend-only) | — | PASS (activity.py:205,257) | PASS | PASS | N/A | — | PASS | VERIFIED (static, API-only) |
| F-08 | Epic lifecycle (create/list/detail/approve/reject/batch-review) | PASS (epics, epics/[id], review) | PASS (epics.py:107,150,175,231,249,283) | PASS (manager) | PASS | LLM-gated planning | spec exists | PASS | VERIFIED (static) |
| F-09 | Epic cost approval (approve-cost → manager relaunch) | PASS (epics/[id] button, lib/api.ts:376) | PASS (epics.py:317) | **BROKEN — relaunch re-halts** | PASS | LLM-gated | — | PASS | **BROKEN** (PROD-12-101) |
| F-10 | Epic policy approval endpoint | — | PASS (epics.py:348) | PASS (policy engine_v2.record_approval) | PASS | N/A | — | PASS | VERIFIED (static, API-only) |
| F-11 | Goals → epics (Executive) | PASS (goals, goals/[id]) | PASS (goals.py 3 routes; lib/api.ts:399–410) | PASS | PASS | LLM-gated | — | PASS | VERIFIED (static) |
| F-12 | Roadmap view + item status | PASS (roadmap; lib/api.ts:568–578) | PASS (roadmap.py 2 routes) | PASS | PASS | N/A | — | PASS | VERIFIED (static) |
| F-13 | Agent execution (manager/dev/qa/reviewer; FleetManager.select) | PASS (tasks/[id] pipeline view) | PASS (agents.py; specialized_agents.py) | PASS | PASS | LLM (UNVERIFIED) | LLM-gated | PASS | VERIFIED (static; runtime LLM-gated) |
| F-14 | Failure recovery / failure ladder (Journey E) | via pipeline state | PASS (fleet/failure_ladder.py; H-1 gap) | PASS | PASS | LLM (UNVERIFIED) | unit tests exist | PASS | PARTIAL (H-1 gap, PROD-12-102) |
| F-15 | Terminal WS inside chat (Journey F) | PASS (TerminalTabs/Panel in chat) | PASS (terminal.py:131 ws) | PASS | PASS | PTY | — | PASS | VERIFIED (static) |
| F-16 | Repository chat (Journey G) | PASS (chat page) | PASS (chat.py:136–421) | PASS (chat_agent + approval gate) | PASS | LLM (UNVERIFIED) | LLM-gated (spec notes) | PASS | VERIFIED (static; runtime LLM-gated) |
| F-17 | Fleet enhancement lifecycle (Journey H) | PASS (fleet page approve/reject) | PASS (fleet_dashboard.py:486,520 → _run_apply_phase:383) | PASS (apply dispatch + impact + rollback, main.py:646) | PASS (EnhancementRequest) | LLM-gated apply | — | PASS (require_approver) | VERIFIED (static; runtime LLM-gated) |
| F-18 | Fleet dashboard (requests/health/stream) | PASS (fleet, NavBar badges) | PASS (fleet_dashboard.py:114–139) | PASS | PASS | N/A | — | PASS | VERIFIED (static) |
| F-19 | Fleet cost report + other reports | — (cost page redirects to /metrics) | PASS (fleet_dashboard.py reports) | PASS | PASS | N/A | — | PASS | PARTIAL (no FE consumer for cost report; hardcoded estimate constants PROD-12-102-adjacent: agents.py:33–34) |
| F-20 | Agent registry page (read) | PASS (agents page) | PASS (registry.py:82–146) | PASS | PASS | N/A | — | PASS | VERIFIED (static) |
| F-21 | Agent create + lifecycle (backend-only) | — | PASS (registry.py:257,290) | PASS | PASS | N/A | — | PASS | VERIFIED (static, API-only) |
| F-22 | Repo management (clone/activate/delete) + onboarding flow | PASS (repo page; onboarding → /repo redirect) | PASS (repo.py:259–386; console clone) | PASS | PASS | git/GitHub (UNVERIFIED) | spec exists | PASS | VERIFIED (static) |
| F-23 | Repo index/graphs (reindex/context/architecture/class-graph/package-graph) | — | PASS (repo.py:506–616) | PASS | PASS | N/A | — | PASS | VERIFIED (static, API-only) |
| F-24 | Metrics dashboard (summary/epics/users) | PASS (metrics page; lib/api.ts:508–534) | PASS (metrics.py 3 routes) | PASS | PASS | N/A | — | PASS | VERIFIED (static) |
| F-25 | Settings / credential vault | PASS (settings page) | PASS (settings.py:45–344) | PASS | PASS | OpenAI verify (UNVERIFIED) | — | PASS | VERIFIED (static) |
| F-26 | Console (git workspace ops) | PASS (console page) | PASS (console.py 13 routes) | PASS | N/A | git (UNVERIFIED) | spec exists | PASS | VERIFIED (static) |
| F-27 | Review page (batch review) | PASS (review page) | PASS (epics.py:175 + decisions) | PASS | PASS | LLM-gated upstream | — | PASS | VERIFIED (static) |
| F-28 | Ratings | PASS (tasks/[id] rate) | PASS (ratings 1 route; lib/api.ts:278) | PASS | PASS | N/A | — | PASS | VERIFIED (static) |
| F-29 | Artifacts + image download | PASS (tasks/[id] links) | PASS (artifacts.py:16,37; tasks.py images) | PASS | PASS | N/A | — | PASS | VERIFIED (static) |
| F-30 | Engineering memory (patterns/lessons/search/analytics/feedback) | — | PASS (memory.py 6 routes) | PASS | PASS | N/A | unit tests | PASS | VERIFIED (static, API-only) |
| F-31 | Privacy / GDPR (export/erase) | — | PASS (privacy.py 3 routes) | PASS | PASS | N/A | — | PASS (admin for cross-user) | VERIFIED (static, API-only) |
| F-32 | Audit log query API | — | PASS (audit.py 5 routes) | PASS | PASS | N/A | — | PASS | VERIFIED (static, API-only) |
| F-33 | Capability-tag dispatch ("zero code change") | — | module exists, unimported | — | SQL-only claim | — | — | — | **UNWIRED** (PROD-12-104) |
| F-34 | Bhaskar specialized agent | — | AGENT_CONTRACT exists | role file absent | — | LLM | — | — | **BROKEN** (PROD-12-103) |

## 3. Wiring Matrix (key features; FE call → BE route verified one by one)

| Feature | UI entry | Frontend call | Backend route | Result |
|---|---|---|---|---|
| Create task | /tasks NewTaskForm | `apiFetch("/api/tasks", POST)` lib/api.ts:122 | tasks.py:171 | MATCH (e2e spec B asserts 201) |
| Task detail stream | /stream/[taskId] | `EventSource(/api/tasks/{id}/stream)` | activity.py:48 | MATCH |
| Stop / resume | /stream/[taskId] | `fetch(...,/stop,/resume POST)` | activity.py:86,101 | MATCH |
| Plan approve/reject | /review, /approvals | `/api/tasks/{id}/pipeline/approve|reject` | tasks.py:762,827 | MATCH |
| Epic batch review | /review | `fetch("/api/epics/batch-review")` | epics.py:175 | MATCH |
| Cost approve | /epics/[id] | `approveCost → /api/epics/{id}/approve-cost` | epics.py:317 | MATCH — but downstream re-halts (PROD-12-101) |
| Chat stream | /chat | `EventSource(/api/chat/sessions/{id}/stream)` | chat.py:215 | MATCH |
| Terminal | /chat tabs | `WebSocket /api/terminal/ws/{sessionId}` | terminal.py:131 | MATCH (protocol comments align) |
| Fleet approve | /fleet | `POST /api/fleet/requests/{id}/{action}` | fleet_dashboard.py:486,520 | MATCH |
| Fleet stream | /fleet, NavBar | `EventSource(/api/fleet/requests/stream)` | fleet_dashboard.py:115 | MATCH (shadowing fix noted at :114) |
| Console ops | /console | 11 calls `${API}/repos/...` | console.py:100–263 | MATCH 11/11 (2 extra routes are clone-private + workspace/mkdir used by /repo page) |
| Repo page | /repo | `/api/console/workspace/browse|mkdir` | console.py:100,113 | MATCH |
| Settings vault | /settings | `/api/settings/openai-key`, `/verify-key` + lib vault calls | settings.py:128,344 | MATCH |
| Metrics | /metrics | `/api/metrics[/epics|/users]` | metrics.py | MATCH |
| Goals / Roadmap | /goals, /roadmap | lib/api.ts:399–410, 568–578 | goals.py, roadmap.py | MATCH |
| Images / artifacts | /tasks/[id] | img src + href to API | tasks.py:1303, artifacts.py:37 | MATCH (GET routes) |

No frontend call to a nonexistent endpoint, no wrong HTTP method, and no wrong-path call was found (all 49 `apiFetch` call sites in `apps/web/lib/api.ts` plus direct `fetch`/`EventSource`/`WebSocket` usage in 16 more files checked against registered routes).

## 4. API Coverage Matrix (summary)

- **FE-consumed:** tasks (20+), epics (6), goals (3), roadmap (2), metrics (3), repo mgmt (4), settings (8), chat (7), fleet (4), console (13), approvals (2), agents (1 GET), ratings (1), artifacts (2), activity (3), auth (3: login/logout/setup).
- **Backend-only (intentional or pending product decision — PROD-12-106):** `/api/auth/me|refresh|change-password` (README: no UI yet); `/api/tasks/{id}/cancel|tokens`; `/api/agents` POST + `/{name}/lifecycle`; `/api/fleet/reports/*` except health; `/api/repo/reindex|context|architecture|class-graph|package-graph`; `/api/memory/*` (6); `/api/privacy/*` (3, admin/DSAR tooling); `/api/audit/*` (5); `/api/specialized_agents/*` (4); `/api/epics/{id}/policy-approval`; `/api/console/repos/clone-private`.
- Every API has an identifiable consumer class (UI, admin/API, or agent-internal); none is consumed by nothing *and* unreachable by design.

## 5. UI Coverage Matrix (21 pages / 6 components)

| Page | Route | Data source | Hardcoded data? | Notes |
|---|---|---|---|---|
| tasks | /tasks | lib/api.ts (real) | no | task list + create |
| tasks/[id] | /tasks/[id] | lib/api.ts | no | pipeline, actions, ratings, images, artifacts |
| stream/[taskId] | /stream/[taskId] | EventSource + fetch | no | stop/resume wired |
| approvals | /approvals | apiFetch direct | no | pending approvals + decisions |
| review | /review | fetch direct | no | batch review + pipeline decisions (fixed by ecd4905a) |
| epics, epics/[id] | /epics, /epics/[id] | lib/api.ts | no | approve/reject/cost buttons |
| goals, goals/[id] | /goals… | lib/api.ts | no | create goal inline |
| roadmap | /roadmap | ../../lib/api | no | item status update |
| metrics | /metrics | @/lib/api | no | 3 endpoints |
| cost | /cost | redirect → /metrics | n/a | no dedicated cost view (F-19 PARTIAL) |
| agents | /agents | fetchAgents | no | read-only registry |
| fleet | /fleet | apiFetch + EventSource | no | enhancement decisions |
| chat | /chat | lib/api.ts + EventSource + WS | no | chat + terminal tabs |
| console | /console | apiFetch `${API}` | no | git ops |
| repo | /repo | fetch direct | no | browse/mkdir/list/clone |
| settings | /settings | fetch + lib | no | vault forms |
| login | /login | lib/auth.ts | no | |
| onboarding | /onboarding | redirect → /repo | n/a | |
| page.tsx | / | redirect → /tasks | n/a | |
| — stream index | /stream (bare) | **no page.tsx — 404** | n/a | PROD-12-105 (E2E tour lists it) |

Components (DiffViewer, NavBar, NewTaskForm, PipelineView, RouteError, StatusBadge, TerminalPanel/Tabs) all receive props from live page data; no mock-data component found.

## 6. E2E Journey Matrix (A–H)

| Journey | Static trace | Existing test artifact | Runtime execution this audit |
|---|---|---|---|
| A — Login → dashboard → protected API → logout → blocked | COMPLETE (middleware PUBLIC_PATHS; HttpOnly cookie; 401 on anonymous) | `journeys.spec.ts` A1–A4 (real stack, committed ecd4905a) | **UNVERIFIED** (backend down; E2E creds absent) |
| B — Create task → repo → mode → submit → backend → DB → UI | COMPLETE (lib/api.ts:122 → tasks.py:171 → list/detail views) | `journeys.spec.ts` B (asserts 201 + persistence via API re-read) | **UNVERIFIED** (same) |
| C — Plan approval (PM→Arch→Decomposer→approve→manager) | COMPLETE paths (approvals.py ↔ approval_gate; tasks pipeline approve) | LLM-gated — intentionally deferred (`PENDING_TESTS_API_KEYS.md`; spec header notes exclusion) | **UNVERIFIED** (paid LLM) |
| D — Agent execution (subtask→agent→worktree→tools→tests→reviewer) | COMPLETE (manager graph, FleetManager.select, specialized dispatch) | LLM-gated (deferred) | **UNVERIFIED** |
| E — Failure recovery (failure→rung→retry/escalation) | Implemented (`fleet/failure_ladder.py`; H-1 exception-path gap) | unit tests exist (test_failure_ladder.py) | **UNVERIFIED** |
| F — Terminal (open→create→exec→stream→exit→cleanup) | COMPLETE (chat tabs → WS terminal.py; close codes aligned) | — | **UNVERIFIED** |
| G — Repo chat (select→ask→context→tools→stream→persist) | COMPLETE (chat.py + chat_agent + approval-gated tools) | LLM-gated (deferred) | **UNVERIFIED** |
| H — Fleet enhancement (request→evidence→approval→apply→tests→commit) | COMPLETE (submit tool → simulate_enhancement_impact → approve → _run_apply_phase → commit_sha → rollback monitor main.py:646) | — | **UNVERIFIED** (LLM-gated apply) |

Static traces are source-level evidence only; per §2.2 they do not prove runtime behavior.

## 7. Feature Counts

- Discovered: **34**
- PRODUCTION_READY: **0** (strict rule: runtime gates unverifiable in read-only mode)
- VERIFIED (static wiring fully evidenced; runtime gate UNVERIFIED): **29**
- PARTIAL: **2** (F-14 failure-path handler gap; F-19 cost view/report)
- BROKEN: **2** (F-09 cost-approval loop; F-34 bhaskar role)
- UNWIRED: **1** (F-33 capability-tag dispatch)
- BLOCKED (feature path needs unavailable external dependency): 0 at feature level; **21 features' runtime executions are blocked** by the environment (backend down / no LLM keys / no E2E credentials)
- CONFLICT: **0**; DEFERRED: **0** (LLM tests deferred, see file 16); UNKNOWN: **0**; REGRESSION: **0** (no repairs performed)

## 8. Findings

### PROD-12-101 — HIGH — Epic cost approval is a dead-end loop (BROKEN)
`backend/app/api/epics.py:317-347` sets `epic.status="pending"` and relaunches `_launch_epic_manager` (same goal, same DB state). `backend/app/agents/manager.py:2036-2126` `_cost_estimate_node` recomputes `estimate_epic_cost(subtask_count=5, db=db)` — deterministic given identical inputs — and, when `estimate.requires_approval`, sets the epic **back** to `pending_cost_approval` (route `_route_after_cost_estimate` → END, manager.py:2532-2535). No persisted or in-flight "cost approved" signal is consumed anywhere (`cost_approved` = 0 grep hits in `backend/`). Net effect: the user's click re-launches the manager and the epic reliably returns to `pending_cost_approval` with the same halt reason. UI button: `apps/web/app/epics/[id]/page.tsx:151-154` → `lib/api.ts:376 approveCost` → `epics.py:317`. Cross-refs: PROD-09-101 (Audit 09). Feature F-09.

### PROD-12-102 — HIGH — manager failure handler abandons the task without terminal transition
`backend/app/api/agents.py:615-620`: on generic exception the handler calls `update_pipeline_state(..., "blocked")`, `append_log`, `send_task_alert` — but **no `transition_task` call**, unlike the success/blocked path immediately above (and the launch_coder pattern at :1043-1048). The task is left mid-state (state "blocked" without terminal bookkeeping), which is exactly the failure-recovery gap of Journey E. Merged finding H-1 (ARCH-01-001 ≡ ORCH-04-101), re-verified OPEN at 90dac23b. Feature F-14.

### PROD-12-103 — HIGH — Bhaskar agent is registered but its role file is missing (BROKEN)
`backend/roles/bhaskar_agent.md` absent (86 role files present, bhaskar not among them); AGENT_CONTRACT/discovery expect a role file per agent, so any routing to bhaskar resolves to an agent that cannot run. Cross-ref AGENT-02-001 (Audit 02). Re-verified ABSENT at 90dac23b. Feature F-34.

### PROD-12-104 — LOW — "zero code change" capability-tag dispatch is unwired
`backend/app/pipeline/dispatcher.py` (docstring promise + `pick_agent_by_tag` "proof point") has zero application importers; production selection is `FleetManager.select()` (fleet_manager.py:78) + `specialized_agents` importlib discovery, not this module. Cross-ref PROD-11-101. Feature F-33 (UNWIRED).

### PROD-12-105 — LOW — bare `/stream` route 404s while the committed E2E page tour expects it to render
`apps/web/app/stream/` contains only `error.tsx` and `[taskId]/` — no `page.tsx`; `/stream` serves Next's 404. `apps/web/e2e-real/journeys.spec.ts` PAGES array lists `"/stream"`, where the assertions (no 5xx, no bounce to /login, no error boundary) pass trivially but the intent (a real page) is unmet. Cosmetic/test-intent mismatch.

### PROD-12-106 — LOW — backend-only surfaces without UI consumers
List in §4 (auth me/refresh/change-password; tasks cancel/tokens; agents create/lifecycle; fleet cost report; repo index/graphs; memory/privacy/audit routers; specialized dispatch; epic policy-approval). Each has a code-documented rationale or is plausibly admin/API/agent-internal, but the product decision (UI vs documented-as-API-only) is pending. Cross-ref PROD-11-103.

**Counts: Critical 0 · High 3 · Medium 0 · Low 3 · Total 6.**

## 9. Runtime Evidence Actually Gathered

```text
curl http://localhost:3100/login  -> 200        (production Next build serving)
curl http://localhost:8000/health -> connection refused (backend DOWN)
ss -ltn -> :5432 Postgres LISTEN, :6379 Redis LISTEN, :3100 LISTEN
git status -> clean worktree; untracked: files/Qoder_audit report/, files/Antigravity_audit_report/, What_is/AUDIT_REPORT/NEXT_PLAN_MONDAY.md
apps/web/e2e-real/journeys.spec.ts present (7 tests: A1,A2,A3,B,page-tour,A4; serial; no mocks)
apps/web/playwright.real.config.ts present (baseURL http://localhost:3100; starts nothing)
PENDING_TESTS_API_KEYS.md present (accounts for all LLM-gated/skipped tests)
```

Not run / not available: backend HTTP 2xx checks; DB queries; Playwright execution (`E2E_USER`/`E2E_PASS` not available); any LLM-dependent journey; browser DOM/screenshot evidence; GitHub clone/push network calls.

To complete the runtime gates (for a future writable pass):
1. Start backend: `.venv/bin/uvicorn app.main:app --port 8000` (Postgres/Redis already up).
2. Create throwaway approver user, then `cd apps/web && npx playwright test -c playwright.real.config.ts` → executes journeys A1–A4, B, page tour against the real stack.
3. With a real `ANTHROPIC_API_KEY`, run the LLM-gated suites per `PENDING_TESTS_API_KEYS.md` and add journeys C, D, E, G, H real-stack specs.

## 10. Green Flag Conditions Checklist

- [ ] Every required feature verified — **NO** (runtime gates unverified)
- [x] Every required feature wired — static side: yes, except F-33 (UNWIRED)
- [x] Backend verified — static route/handler level yes; runtime no
- [x] Frontend verified — static call-site level yes; browser no
- [ ] Database verified — no live queries performed this audit
- [ ] Runtime verified — **NO** (backend down, LLM-gated)
- [x] Security verified — static (auth deps present on all routes; prior security audit 88/100)
- [ ] E2E verified — suite exists and is committed, but was not executed
- [ ] Regression verified — no repairs performed (read-only), so nothing to regress
- [x] No critical unknowns — critical paths statically traced
- [ ] No unresolved critical defects — none critical; but 2 HIGH feature defects open (PROD-12-101/102/103)
- [x] No unresolved feature/API wiring gaps — apart from F-33 (UNWIRED) and the documented backend-only surface

**FINAL STATUS: NOT GREEN — PRODUCTION FEATURE AUDIT INCOMPLETE** (read-only constraint; zero critical defects; 2 broken feature paths + 1 unwired capability carried forward).

## 11. Evidence Index (spot references)

- `apps/web/lib/api.ts` (49 endpoint calls; apiFetch chokepoint :15) — lines cited in §3.
- `apps/web/app/*` pages and `apps/web/components/*` — call sites per §3/§5.
- `backend/app/api/activity.py:48,86,101,205,257`; `tasks.py:171-1322`; `epics.py:107-348`; `fleet_dashboard.py:114-520`; `chat.py:136-421`; `console.py:100-263`; `settings.py:45-344`; `terminal.py:131`; `auth.py:66-219`; `artifacts.py:16,37`; `repo.py:259-616`; `registry.py:82-290`; `memory.py:41-247`; `privacy.py:103-132`; `audit.py:57-99`.
- `backend/app/agents/manager.py:2036-2126,2532-2535,2627`; `backend/app/agents/agents.py` (`api/agents.py`):33-34, 613-620, 1043-1048.
- `backend/app/pipeline/dispatcher.py` (1-120); `backend/app/api/specialized_agents.py:200-227`.
- `apps/web/e2e-real/journeys.spec.ts` (1-130); `apps/web/playwright.real.config.ts`; `PENDING_TESTS_API_KEYS.md`.
