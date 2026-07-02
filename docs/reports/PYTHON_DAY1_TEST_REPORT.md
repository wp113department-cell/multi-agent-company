# Python Backend Day 1 Test Report

**Date:** 2026-07-02
**Phase:** Python Backend Rebuild — Day 1 (Foundation)

## What Was Built

Full Python backend foundation replacing the TypeScript packages (archived in `TX/`).

### Stack
- Python 3.12.3
- FastAPI 0.139.0 + Uvicorn 0.49.0
- Pydantic Settings 2.14.2 (config/env validation)
- SQLAlchemy 2.0.51 + asyncpg 0.31.0 (async ORM)
- Alembic 1.18.5 (migrations)
- LangGraph 1.2.7 + langchain-anthropic 1.4.8 (installed, wired in Day 2)
- Anthropic 0.115.1 + Voyage AI 0.4.1 (installed, wired in Day 2)
- pytest 9.1.1 + pytest-asyncio 1.4.0
- mypy 2.1.0 + ruff 0.15.20 + black 26.5.1

### Files Created

**Core:**
- `backend/requirements.txt` — pinned production deps
- `backend/requirements-dev.txt` — pinned dev/test deps
- `backend/pytest.ini` — pytest config (asyncio_mode=auto)
- `backend/mypy.ini` — mypy strict mode config
- `backend/alembic.ini` — Alembic migration config

**App:**
- `backend/app/__init__.py`
- `backend/app/config.py` — Pydantic BaseSettings (all config from env, crash on missing required)
- `backend/app/main.py` — FastAPI app, CORS, router registration, health endpoint
- `backend/app/db/__init__.py`
- `backend/app/db/models.py` — SQLAlchemy 2.0 Mapped[] ORM models (DevTask, TaskLog, AgentRun, Subtask, PipelineState, IndexedFile, Symbol, CallEdge) + VALID_TRANSITIONS + can_transition()
- `backend/app/db/session.py` — async engine + session factory + get_db() FastAPI dependency
- `backend/app/db/repository.py` — full CRUD: create_task, list_tasks (cursor pagination), transition_task, append_log, create_agent_run, heartbeat_agent_run, finish_agent_run, save_subtasks, pipeline state management
- `backend/app/api/__init__.py`
- `backend/app/api/tasks.py` — FastAPI routes: POST/GET /api/tasks, GET/PATCH /api/tasks/:id, POST /api/tasks/:id/logs, GET /api/tasks/:id/logs, POST /api/tasks/:id/approve, POST /api/tasks/:id/reject, GET /api/tasks/:id/subtasks, POST /api/tasks/:id/run
- `backend/app/api/repo.py` — POST/GET /api/repo/reindex (stub — wired in Day 2)
- `backend/app/policy/__init__.py`
- `backend/app/policy/engine.py` — check_path(), check_command(), check_path_in_worktree() — pure functions, path component matching
- `backend/app/repo_tools/__init__.py`
- `backend/app/repo_tools/worktree.py` — create_worktree(), get_diff(), remove_worktree()
- `backend/app/agents/__init__.py`
- `backend/app/pipeline/__init__.py`
- `backend/app/mcp/__init__.py`

**Migrations:**
- `backend/migrations/env.py` — async Alembic env
- `backend/migrations/script.py.mako` — migration template
- `backend/migrations/versions/001_initial_schema.py` — full schema: dev_tasks, task_logs, agent_runs, subtasks, pipeline_state, indexed_files, symbols, call_edges, code_embeddings (pgvector)

**Roles:**
- `backend/roles/planner.md`
- `backend/roles/pm.md`
- `backend/roles/architect.md`
- `backend/roles/decomposer.md`
- `backend/roles/coder.md`

**Archive:**
- `TX/` — all 11 TypeScript packages archived here (reference only)

## Test Commands Run

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://..." ANTHROPIC_API_KEY="sk-ant-dummy" .venv/bin/pytest tests/ -v
DATABASE_URL="postgresql+asyncpg://..." ANTHROPIC_API_KEY="sk-ant-dummy" .venv/bin/mypy app/ --ignore-missing-imports
```

## Results

### pytest — 43/43 PASS

| File | Tests | Result |
|---|---|---|
| tests/test_config.py | 3 | ✅ PASS |
| tests/test_status_transitions.py | 11 | ✅ PASS |
| tests/test_policy.py | 29 | ✅ PASS |

### mypy — CLEAN
```
Success: no issues found in 17 source files
```

## Status Transition Coverage (11 tests)
- pending → planning ✅
- pending → completed (blocked) ✅
- planning → ready_for_review ✅
- ready_for_review → coding ✅
- coding → testing ✅
- testing → ready_for_review ✅
- completed has no valid transitions ✅
- failed has no valid transitions ✅
- blocked → planning (restart) ✅
- completed → pending (blocked) ✅
- invalid status → any (blocked) ✅

## Policy Engine Coverage (29 tests)
**check_path — denied:** .env, .env.local, .env.production, secrets/ directory, .github/workflows/, nested .github/workflows/
**check_path — allowed:** normal source files, README, package.json
**check_command — denied:** rm -rf, kubectl, terraform, git push, git push --force, docker push, npm publish, pnpm publish, vercel deploy, heroku, wget/curl http
**check_command — allowed:** pytest, mypy, ruff, ls
**check_path_in_worktree:** relative inside ✅, absolute inside ✅, path traversal ../../ blocked ✅, absolute outside blocked ✅, .env inside worktree still denied ✅

## Known Issues / Pending
- Integration tests (DB-backed CRUD) require live Postgres — run with real DATABASE_URL
- Day 2: LangGraph pipeline, base agent runner, repo intelligence (tree-sitter), Voyage AI embeddings, MCP server

## Verdict
✅ PASS — Python Day 1 Foundation: 43/43 tests, mypy clean
