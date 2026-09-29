# Audit 01: Master Architecture Audit

**Spec:** `files/Audit/01_MASTER_ARCHITECTURE_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **Baseline commit:** `ef982bf8` · **JSON sidecar:** `json/AUDIT_01_ARCHITECTURE.json`

## Result

🟢 **GREEN: architecture verified; all defects found were fixed and regression-tested.**

**Architecture score: 92 / 100.** The structure matches its design: two graphs, both checkpointed; the correct task id at every event call site; one migration head; no real import cycles; historical fixes still holding. Points lost for one real High bug (now fixed), frontend/backend drift on the login page (fixed), and one dead legacy module that the documentation described as the live dispatcher (the documentation is now fixed).

## Executive summary

The system is what it claims to be: a FastAPI backend with two separate LangGraph graphs, a Fleet OS layer, and a Next.js frontend, joined by 21 routers and 143 API operations. The audit found **one High-severity bug** in the failure-recovery path: whenever an epic halted, or a subtask ran out of retries, the recovery code crashed silently. That is now fixed and proven with un-mocked tests. It also found and fixed a **developer-login shortcut with the dev admin password shipping inside the production login bundle**, and a dead "Set up admin account" link. Everything else checked came out clean, with evidence below.

## 1. System diagram (traced in code, not taken from docs)

```
Browser (Next.js 15, apps/web)
  │  apiFetch() → /api/*   (lib/api.ts; JWT cookie; 73/79 call sites map 1:1 to OpenAPI ops)
  ▼
FastAPI app (backend/app/main.py:1812) ── 21 routers, 128 paths / 143 operations
  │
  ├─ (a) simple mode:  POST /api/tasks/{id}/run  (mode="simple")
  │        → dispatch_job(launch_planner)        app/api/tasks.py:317
  │        → human approves → launch_coder       app/api/agents.py
  │
  ├─ (b) full mode:    POST /api/tasks/{id}/run  (mode="full")
  │        → launch_planning_pipeline → pipeline/graph.py:
  │             pm_node → architect_node → decomposer_node → human_review (interrupt())
  │        → POST /api/approvals/{thread}/approve → resume → launch_manager
  │        → run_manager(): topological waves → backend_dev|frontend_dev → git commit → QA → Reviewer
  │        → task: testing → ready_for_review | blocked (+ alert)
  │
  └─ (c) chat:         POST /api/chat/sessions/{id}/messages → ChatAgent (SSE stream)

Every agent run → base_graph.run_agent_graph() → Anthropic (circuit breaker, config timeout/retries)
Events → fleet_events.publish() → event_bus (in-process; optional Redis Streams) → SSE / DB
State  → Postgres 16 + pgvector (43 ORM tables + 8 infra/raw-SQL tables), LangGraph checkpoints
```

## 2. Two-graph map

| Graph | File | Nodes | Checkpointer | Who runs under it |
|---|---|---|---|---|
| Epic planning graph | `app/pipeline/graph.py` | `pm` → `architect` → `decomposer` → `human_review` (`interrupt()`) | `AsyncPostgresSaver` (survives restarts) | pm, architect, decomposer (as nodes) |
| Per-agent graph | `app/agents/base_graph.py` `run_agent_graph()` | planner → memory_hook → call_llm → reflection → execute_tools (1 tool per step) → … | **Also** `AsyncPostgresSaver` now (`init_agent_checkpointer`, `base_graph.py:69`), with a MemorySaver fallback | all other 82 registered agents |
| Manager | `app/agents/manager.py` | plain async orchestration, **not** a LangGraph node (confirmed) | n/a (uses the per-agent graph for each worker) | manager |

**Two-graph verdict:** correct. The audit spec assumed "base_graph agents have no checkpointer"; that is outdated. The T2-B2 work added a real Postgres checkpointer and `resume_trace_id`, so nothing wrongly assumes resume semantics.

## 3. Event / trace-id verdict: VERIFIED CLEAN

- Exactly **8** `FleetEventType` values (`fleet_events.py:38-46`); no 9th type invented. `tests/test_event_compliance.py`: 3/3 pass.
- Every `task_started` / `task_completed` / `task_failed` / `task_created` / `review_requested` call site passes the real task id (`base_graph.py:3770,4171,4238`, `manager.py:435`, `api/agents.py:106-130`, `failure_ladder.py:155,184`). The historical `task_id=tid` bug has not come back.

## 4. Structure checks

| Check | Result | Evidence |
|---|---|---|
| Import cycles (module-level, AST-built graph of 493 modules) | ✅ Only `app.event_bus` ↔ `app.event_bus.bus`, a normal package re-export | `evidence/import_graph.py` |
| Orphan modules | ⚠️ 1 dead file: `app/fleet/providers/base.py` (unused ABC, 0 references anywhere). 1 legacy module: `app/pipeline/dispatcher.py` (used by tests only). All agent modules are loaded dynamically, so they are not orphans. | `evidence/import_graph.out.json` |
| Migrations | ✅ single head `062`, DB at head | `alembic heads` / `alembic current` |
| ORM ↔ DB drift | ✅ 0 ORM tables missing from the DB; the 3 DB-only tables (`audit_log`, `chat_messages`, `lessons`) are used through raw SQL, each with its own migration | DB diff script |
| Historical hardcoding fixes | ✅ CORS origins (`main.py:1823`), event-bus retries (`event_bus/bus.py:39`), Groq retries (`groq_adapter.py`): all still config-driven | code |
| Groq isolated from tests | ✅ `tests/conftest.py:66` forces `USE_GROQ=false` | code |
| Frontend ↔ backend contract | ✅ after fix: 79 frontend API call sites extracted with the TypeScript compiler AST; 79/79 map to a real backend operation | `evidence/fe_api_calls.cjs`, `evidence/fe_be_contract.py` |

## 5. Findings (evidence schema, `00b_AUDIT_STANDARDS.md`)

- **id:** ARCH-01-001 · **severity:** High · **status: FIXED**
  **file:** `backend/app/fleet/failure_ladder.py` · **location:** `abort()`, `request_human_review()` · **line:** 140-205 (pre-fix)
  **finding:** Both functions called bare `asyncio.run()`. Their only callers in the manager (`manager.py:1727, 1748`) sit inside `async def run_manager()`, so every call raised `RuntimeError: asyncio.run() cannot be called from a running event loop`. The manager's `except Exception: pass` swallowed it. When an epic halted, or a subtask exhausted its retries, no `TaskFailed` / `ReviewRequested` event was ever published.
  **evidence:** reproduced before the fix: `abort RAISED: RuntimeError asyncio.run() cannot be called from a running event loop` (same for `request_human_review`). The existing manager tests patched both functions with mocks, which is why this never surfaced.
  **production_impact:** Recovery events and their downstream observability were silently lost on exactly the failure paths operators care about.
  **fix:** `_transition_task_sync()` runs the DB transition on a short-lived worker thread when a loop is already running. A new `transition=False` option lets the manager publish the events without touching the status, because `launch_manager` already owns the final status (blocked + alert), so user-visible behaviour is unchanged. Silent `except: pass` replaced with `logger.warning(..., exc_info=True)`.
  **verification:** `tests/test_audit01_failure_ladder_in_event_loop.py` (4 tests, real DB, real `run_manager()`, ladder not mocked) plus 118 existing manager/epic tests: all pass.
  **confidence:** High · **effort:** Small

- **id:** ARCH-01-002 · **severity:** Medium · **status: FIXED**
  **file:** `apps/web/app/login/page.tsx` · **location:** `DEV_LOGIN_*`, "Developer Login" button · **line:** 7-14, 112-131 (pre-fix)
  **finding:** A "Developer Login" button and the dev admin credentials (`admin` / `gridiron123`) were compiled into the **production** login bundle. The code's own comment said "REMOVE … before shipping to real users."
  **evidence:** `grep -rl gridiron123 .next/static` → `.next/static/chunks/app/login/page-*.js` (pre-fix).
  **production_impact:** Publishes the default admin password to every visitor. The backend already rejects `gridiron123` when `DEPLOYMENT_ENV=production` (`config.py:1996`), so this is a leak and a broken button in production, and an instant login on any non-production deployment exposed to a network.
  **fix:** The button and credentials exist only when `process.env.NODE_ENV === "development"` (inlined at build time). `run.sh` uses `next dev`, so the owner's local shortcut still works.
  **verification:** production rebuild → 0 bundles contain `gridiron123` or "Developer Login"; `app/login/page.test.tsx` (3 tests) checks both modes.
  **confidence:** High · **effort:** Small

- **id:** ARCH-01-003 · **severity:** Medium · **status: FIXED**
  **file:** `apps/web/app/login/page.tsx` · **line:** 135 (pre-fix)
  **finding:** The "Set up admin account" link did a browser GET on `/api/auth/setup`, which is POST-only, and returns 409 once the admin is auto-seeded at startup (`main.py:1545-1564`) and 404 in production. The link could never work in any environment.
  **evidence:** OpenAPI: `['post'] /api/auth/setup`; `evidence/fe_be_contract.out.json`.
  **fix:** replaced with an accurate hint (sign in as `admin` with `DEFAULT_ADMIN_PASSWORD`); covered by `app/login/page.test.tsx`.
  **confidence:** High · **effort:** Small

- **id:** ARCH-01-004 · **severity:** Low · **status: FIXED (documentation)**
  **file:** `backend/app/pipeline/dispatcher.py` · **line:** 1-163
  **finding:** The guide called this "the topological subtask dependency dispatcher", but no production code imports it. Real ordering is `manager._topological_subtask_order/_waves` and real selection is `fleet_manager.select()`.
  **fix:** guide corrected; the module is left in place because its tests pin the legacy fallback map (removing it has no production benefit).
  **confidence:** High · **effort:** Small

- **id:** ARCH-01-005 · **severity:** Low · **status: OPEN → handled in audit 11 (dead code)**
  **file:** `backend/app/fleet/providers/base.py` · **line:** 1-39
  **finding:** `LLMProvider` ABC with zero references in `app/`, `tests/` or `scripts/`.
  **confidence:** High · **effort:** Small

- **id:** ARCH-01-006 · **severity:** Low · **status: FIXED**
  **file:** `backend/app/agents/gemini_adapter.py` · **line:** 347-351
  **finding:** `response.candidates[0]` crashed with an opaque `TypeError` when Gemini returned no candidates (for example a safety block); also flagged by `mypy --strict` (3 errors).
  **fix:** explicit `RuntimeError` naming the prompt feedback; `mypy --strict` back to 0 errors.
  **confidence:** High · **effort:** Small

## 6. Config sprawl

Historical fixes all hold (§4). A full hardcoding sweep is in audit 11.

## 7. Technology fit

All major libraries in `requirements.txt` / `package.json` are used for their documented purpose; installed versions match the guide (`00_MASTER_GUIDE_VERIFICATION.md` §1). No framework swaps are recommended.

## 8. Verdict for next phase

**READY:** no open Critical or High issues in this layer.
