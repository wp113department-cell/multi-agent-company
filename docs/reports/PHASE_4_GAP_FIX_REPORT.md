# Phase 1–4 Gap Fix Report

**Date:** 2026-07-02  
**Session:** Gap analysis + fix pass (Phase 1–4 line-by-line audit)

## Commands Run

```bash
cd backend
.venv/bin/python -m pytest tests/ -v --tb=short -q
.venv/bin/python -m mypy app/ --strict
```

## Results

### pytest
```
170 tests collected
123 passed
47 skipped (pending — require RUN_PENDING_TESTS=1 + API keys)
0 failed
0 errors

Time: 4.77s
```

### mypy --strict
```
Success: no issues found in 43 source files
```

---

## Gaps Fixed

### Gap 1 — LOG_LEVEL env var (Phase 1)
**Files:** `backend/app/config.py`, `backend/.env.example`

Added `log_level: str = Field(default="INFO")` to `Settings`. Applied in `main.py` lifespan via `logging.basicConfig(level=settings.log_level.upper())`.

---

### Gap 2 — Token tracking not persisted (Phase 2)
**Files:** `backend/app/agents/planner.py`, `backend/app/agents/coder.py`, `backend/app/api/agents.py`

`run_planner()` and `run_coder()` now return `4-tuples`: `(result, error, tokens_in, tokens_out)` with accumulated tokens across all retry attempts. `launch_planner()` and `launch_coder()` in `agents.py` now call `finish_agent_run(db, run_id, status, tokens_in=ti, tokens_out=to, cost_estimate=cost)`. Cost estimate uses Haiku pricing ($0.80/M input, $4.00/M output).

---

### Gap 3 — Structured error responses (Phase 1)
**File:** `backend/app/main.py`

Added FastAPI exception handlers for `StarletteHTTPException` and `RequestValidationError` that return `{ error: { code, message } }` format — matching the frontend `api.ts` `handleResponse()` shape.

---

### Gap 4 — Weekly auto-reindex scheduler (Phase 3)
**File:** `backend/app/main.py`

Added `_weekly_reindex_loop()` async background task started in `lifespan`. Sleeps 7 days, then calls `index_repository()` + `invalidate_context_cache()`. Cancelled cleanly on shutdown.

---

### Gap 5 — MCP missing semantic_search + get_file_summary tools (Phase 3)
**File:** `backend/app/mcp/server.py`

Added two new MCP tools to `_TOOLS` manifest and `_handle()` dispatcher:
- `semantic_search(query, repo_path, top_k)` — keyword-based scoring over symbols + file paths (graceful fallback when Voyage embeddings not pre-built)
- `get_file_summary(file_path, repo_path)` — returns symbols, language, imports for a file

---

### Gap 6 — Artifacts never written to disk/DB during pipeline (Phase 4)
**Files:** `backend/app/api/agents.py`, `backend/app/artifacts/store.py`

`launch_planning_pipeline()` now calls `save_artifact_async()` for `pm_brief`, `architect_plan`, and `subtasks` after the LangGraph pipeline runs (with DB session, so metadata persisted). `launch_coder()` saves the `diff` artifact. `launch_manager()` saves `review_findings` per subtask + the final `diff`.

Added `"subtasks"` to `ARTIFACT_TYPES` frozenset in `store.py`.

---

### Gap 7 — Artifact API used `db=None` (artifacts always empty) (Phase 4)
**File:** `backend/app/api/artifacts.py`

Fixed `list_task_artifacts()` to inject `db: AsyncSession = Depends(get_db)` so `list_artifacts()` queries the real DB. Fixed response field name from `type` → `artifactType` to match frontend `ArtifactRecord` interface.

---

### Gap 8 — Pipeline approve → single coder instead of manager (Phase 4)
**File:** `backend/app/api/agents.py`

`resume_planning_pipeline()` now calls `asyncio.create_task(launch_manager(task_id, subtasks, plan))` instead of `launch_coder()`. Added `launch_manager()` which:
1. Creates git worktree
2. Updates pipeline stage to `"dev_running"`
3. Transitions task to `"coding"`
4. Awaits `run_manager()` with `on_status` callback for log entries
5. On completion: saves diff + review_findings artifacts, transitions task to `ready_for_review`
6. On block: transitions to `"blocked"`, preserves worktree

---

### Gap 9 — manager.py blocking the event loop (Phase 4)
**File:** `backend/app/agents/manager.py`

Wrapped sync agent calls in `asyncio.to_thread()`:
- `run_backend_dev()` → `await asyncio.to_thread(run_backend_dev, ...)`
- `run_frontend_dev()` → `await asyncio.to_thread(run_frontend_dev, ...)`
- `run_qa()` → `await asyncio.to_thread(run_qa, ...)`
- `run_reviewer()` → `await asyncio.to_thread(run_reviewer, ...)`

---

### Gap 10 — Stage 4 UI missing Dev→QA→Review display (Phase 4)
**File:** `apps/web/components/PipelineView.tsx`

Added new pipeline stage labels for `"dev_running"`, `"qa_running"`, `"review_running"`, `"dev_complete"`. Added "Coding Pipeline" section that renders when `stage` is in `CODING_STAGES` or `"dev_complete"`. Shows three stage chips (Dev Agent → QA Agent → Reviewer) with active pulse animation and green checkmarks for completed stages.

---

### Gap 11 — No artifact inspector in task detail page (Phase 4)
**Files:** `apps/web/app/tasks/[id]/page.tsx`, `apps/web/lib/api.ts`

Added `fetchArtifacts(taskId)` to `api.ts` with `ArtifactRecord` interface. Added `useQuery` for artifacts in task detail page (polls every 5s). Shows "Pipeline Artifacts" section with `artifactType` badge, agent name, timestamp, and "View" link to `/api/artifacts/:id`.

---

## Gaps Left (require credentials or major infra changes)

| Gap | Reason deferred |
|---|---|
| Postgres checkpointer (MemorySaver loses state on restart) | Requires `langgraph-checkpoint-postgres` + live Postgres at dev time |
| Context cache as DB table | In-memory cache works; DB cache is a Phase 5 optimisation |
| Playwright E2E tests | Requires full browser + live server + API keys |
| Agent eval tests (3-5 real tasks) | In `tests/pending/` — require `ANTHROPIC_API_KEY` |
| Bash allowlist from config | Security: denylist should not be user-configurable; kept hardcoded |

---

## Verdict

✅ GREEN FLAG — PHASE 1–4 GAP FIX COMPLETE

- 123/123 non-pending tests pass
- 47/47 pending tests skip cleanly
- mypy --strict: 0 issues in 43 files
- 11 functional gaps fixed across Phases 1–4
- Token tracking now wired end-to-end (DB stores tokens_in, tokens_out, cost_estimate)
- Full multi-agent pipeline path now wired: Plan Approval → Manager → Dev→QA→Review per subtask
- Artifacts written and queryable for every pipeline stage
- Dev→QA→Review UI visible in PipelineView with live stage indicators
- Weekly auto-reindex background loop running
