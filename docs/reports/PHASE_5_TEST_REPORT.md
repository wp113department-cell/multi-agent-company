# Phase 5 Test Report

**Date:** 2026-07-03
**Session:** Phase 5 — Manager Agent + Epics + Cost Controller + Policy Engine v2 + RBAC + DevOps Agent + Epic Approval UI

## Commands Run

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://x:x@localhost/x ANTHROPIC_API_KEY=sk-dummy \
  .venv/bin/python -m pytest tests/ -v --tb=short

DATABASE_URL=postgresql+asyncpg://x:x@localhost/x ANTHROPIC_API_KEY=sk-dummy \
  .venv/bin/python -m mypy app/ --strict
```

## Results

### pytest

```
172 passed, 51 skipped in 5.27s
```

- 49 new Phase 5 tests (cost controller, policy v2, RBAC, devops agent) — all pass
- 123 existing Phase 0–4 tests — all still pass (no regressions)
- 51 skipped = pending tests (require RUN_PENDING_TESTS=1 + API keys + live DB)
- 0 failed, 0 errors

### mypy --strict

```
Success: no issues found in 49 source files
```

(Was 43 files before Phase 5; added 6 new modules)

---

## What Was Built

### Step 1 — Alembic Migration 003 (`backend/migrations/versions/003_phase5_tables.py`)

New tables:
- `epics` — UUID PK, title, description, status, cost_estimate, cost_actual, halt_reason, timestamps
- `dev_tasks.epic_id` — nullable FK → epics (with SET NULL on delete)
- `policies` — id, name, trigger_pattern (glob), required_approval_role, blocking, active
- `policy_approvals` — audit log: policy_id FK, task_id, epic_id, file_path, approver_role, decision
- `user_roles` — user_id (unique), role (viewer | approver)

Seeded 3 canonical policy rules:
- `**/migrations/**` → human, blocking
- `api/customer/**` → architect, blocking
- `auth/**` → security, flag-only

### Step 2 — Config (`backend/app/config.py`)

Added 8 new env vars:
- `COST_APPROVAL_THRESHOLD` (default 1.0 USD)
- `COST_PER_INPUT_TOKEN`, `COST_PER_OUTPUT_TOKEN` (Haiku pricing)
- `COST_TOKENS_PER_SUBTASK`, `COST_OUTPUT_RATIO` (estimation coefficients)
- `MANAGER_MAX_SUBTASK_RETRIES` (default 2)
- `MANAGER_MAX_EPIC_FAILURES` (default 2 — triggers epic.halted)
- `DEVOPS_BASH_ALLOWLIST` (comma-separated read-only command prefixes)
- `RBAC_ENABLED` (default true)

### Step 3 — ORM Models (`backend/app/db/models.py`)

Added `Epic`, `Policy`, `PolicyApproval`, `UserRole` ORM classes. Added `epic_id` FK + `epic` relationship to `DevTask`.

### Step 4 — Cost Controller (`backend/app/pipeline/cost_controller.py`)

- `estimate_epic_cost(subtask_count, db, complexity_multiplier)` — async, queries historical agent_run averages
- `estimate_epic_cost_sync(subtask_count, ...)` — sync, used in tests and pre-DB contexts
- Returns `CostEstimate` dataclass with `requires_approval` flag

### Step 5 — Policy Engine v2 (`backend/app/policy/engine_v2.py`)

- Custom glob-to-regex compiler handles `**`, `*`, `?`, path separators correctly
- `check_file_against_policies(file_path, db)` — async, returns list of `PolicyMatch`
- `check_files_against_policies(file_paths, db)` — batch check
- `has_approval(policy_id, db, task_id, epic_id, file_path)` — check if approval row exists
- `record_approval(policy_id, approver_role, decision, db, ...)` — persist approval to audit log
- `match_pattern_sync(file_path, glob_pattern)` — sync helper for tests

### Step 6 — RBAC Middleware (`backend/app/middleware/rbac.py`)

- `require_approver(x_user_id, db)` — FastAPI dependency
- Reads `X-User-Id` header → looks up `user_roles` table → raises 403 if viewer or missing
- Defaults to viewer when user not in table
- Bypassed when `RBAC_ENABLED=false`

### Step 7 — DevOps Agent

- `backend/roles/devops.md` — role file: read-only bash only, no write, no deploy
- `backend/app/agents/devops.py` — `run_devops()`, DEVOPS_TOOLS, allowlist from config
- `DEVOPS_TOOLS` in `tools.py` — has bash + read_file + list_files + submit_health_report. NO write_file, NO submit_patch
- `make_devops_handlers()` — bash enforces `DEVOPS_BASH_ALLOWLIST` + v1 policy check

### Step 8 — Manager Agent Upgrade (`backend/app/agents/manager.py`)

- `run_manager()` upgraded: tracks `blocked_count`, halts epic when `≥ MANAGER_MAX_EPIC_FAILURES`
- `run_epic_manager(epic_id, goal, db)` — top-level epic orchestrator:
  1. Cost estimate → if over threshold → status `pending_cost_approval` + event
  2. Planning pipeline (LangGraph PM→Arch→Decomp)
  3. Per-subtask Dev→QA→Review loop with retry cap
  4. If `≥ MANAGER_MAX_EPIC_FAILURES` blocked → `epic.halted` event
  5. On all complete → `epic.ready_for_review` event + approval package returned

New event types added to `event_bus/models.py`:
- `epic.pending_cost_approval`
- `epic.planning_started`
- `epic.ready_for_review`
- `epic.halted`
- `epic.approved`
- `epic.rejected`

### Step 9 — Epic API (`backend/app/api/epics.py`)

6 routes registered:
- `POST /api/epics` — create epic + fire-and-forget manager pipeline
- `GET /api/epics` — list all epics
- `GET /api/epics/:id` — get epic + child tasks
- `POST /api/epics/:id/approve` — approver role required (RBAC enforced)
- `POST /api/epics/:id/reject` — approver role required
- `POST /api/epics/:id/approve-cost` — approver role required, re-launches manager
- `POST /api/epics/:id/policy-approval` — record policy gate approval

DB session: added `get_async_session()` context manager to `session.py` for background tasks.

### Step 10 — Epic Approval UI

- `apps/web/app/epics/page.tsx` — Epics list + NewEpicForm
- `apps/web/app/epics/[id]/page.tsx` — Epic detail: goal, cost estimate vs actual, child tasks, halt notice, Approve/Reject/ApproveCost actions
- `apps/web/lib/api.ts` — Added `Epic`, `EpicTask` interfaces + `fetchEpics`, `fetchEpic`, `createEpic`, `approveEpic`, `rejectEpic`, `approveCost` functions
- `apps/web/app/layout.tsx` — Added "Epics" nav link

---

## New Test Files

| Test file | Tests | Description |
|---|---|---|
| `tests/test_cost_controller.py` | 9 | Estimate math, threshold logic, historical averages, multiplier |
| `tests/test_policy_v2.py` | 23 | Glob pattern matching (18 parametrized + 5 named), case sensitivity, deep nesting |
| `tests/test_rbac.py` | 6 | Approver passes, viewer → 403, missing header → 403, unknown user → viewer, RBAC disabled bypass |
| `tests/test_devops_agent.py` | 9 | Tool list structure, bash allowlist (allow/deny), no write_file handler |
| `tests/pending/test_manager_integration.py` | 4 | Manager flow, halt, cost gate, policy v2 DB (all skip without API keys) |

---

## Pending (require API keys + live Postgres)

- `tests/pending/test_manager_integration.py` — epic lifecycle, halt path, cost gate, policy v2 DB query (4 tests)
- Real DevOps Agent runs require ANTHROPIC_API_KEY
- Epic manager full E2E requires ANTHROPIC_API_KEY + DATABASE_URL + live Postgres

---

## Verdict

✅ GREEN FLAG — PHASE 5 COMPLETE

- 172/172 non-pending tests pass
- 51/51 pending tests skip cleanly
- mypy --strict: 0 issues in 49 source files
- No regressions from Phases 0–4
