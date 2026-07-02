# Phase 4 Test Report

**Date:** 2026-07-02  
**Phase:** 4 — Specialist Agents + QA Loop + Event Bus + Artifact Store  
**Branch:** main

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

Time: 4.84s
```

### mypy --strict

```
Success: no issues found in 43 source files
```

## Test Breakdown

### New Phase 4 tests (all passing)

| Test File | Tests | Purpose |
|---|---|---|
| `tests/test_event_bus.py` | 15 | Publish/subscribe roundtrip, per-task ordering, retry on handler failure, sync handlers, failed handler isolation |
| `tests/test_artifacts.py` | 8 | Save string/dict content, get content, roundtrip, multiple artifacts, list_artifacts without DB |
| `tests/test_dispatcher.py` | 9 | Routing table (backend/frontend/test/docs/unknown), dispatch to correct agent, QA failure returns error |
| `tests/test_tool_scoping.py` | 28 | Doc-07 matrix compliance: QA has no write_file, Reviewer has no bash/write_file, QA bash allowlist (9 allowed, 8 denied), full matrix check |

### Existing tests (regression — all passing)

| Test File | Tests |
|---|---|
| `tests/test_context_builder.py` | 5 (fixed: removed unused `get_settings()` call) |
| `tests/test_policy.py` | 28 |
| `tests/test_scanner.py` | 9 |
| `tests/test_status_transitions.py` | 12 |
| `tests/test_mcp.py` | 6 |
| `tests/test_config.py` | 3 |

### Pending tests (47 skipped)

All skip cleanly without `RUN_PENDING_TESTS=1`. New: `test_specialist_agents.py` (9 tests) covering:
- Backend dev reads/writes files correctly
- Backend dev cannot escape worktree boundary (policy enforcement)
- QA agent runs pytest and produces structured QAResult
- QA structurally cannot write files (tool list check)
- Reviewer produces structured ReviewFinding list
- Reviewer structurally has no write_file or bash
- Full Dev → QA → Review happy path
- QA failure → dev retry loop
- Manager orchestrates multiple subtasks

## What Was Built

### Role files
- `backend/roles/backend_dev.md` — safety rules, tools: Read+Write+Bash(typecheck/lint), submit_patch
- `backend/roles/frontend_dev.md` — same scope, Next.js/TypeScript focus
- `backend/roles/qa.md` — Read+Bash(tests only), no write, submit_qa_result
- `backend/roles/reviewer.md` — Read only, submit_review with typed findings schema
- `backend/roles/manager.md` — orchestration only, no write, dispatches subtasks

### Specialist agents
- `backend/app/agents/backend_dev.py` — `run_backend_dev()`, CODER_TOOLS, self-correction loop
- `backend/app/agents/frontend_dev.py` — `run_frontend_dev()`, CODER_TOOLS, tsc typecheck
- `backend/app/agents/qa.py` — `run_qa()` → `QAResult`, QA_TOOLS (no write)
- `backend/app/agents/reviewer.py` — `run_reviewer()` → `ReviewResult`, REVIEWER_TOOLS (read only)
- `backend/app/agents/manager.py` — `run_manager()`, orchestrates Dev→QA→Review with retry cap

### Tool scoping (doc-07 matrix enforced structurally)
- `QA_TOOLS` — READ_ONLY_TOOLS + bash(test allowlist) + submit_qa_result, NO write_file
- `REVIEWER_TOOLS` — READ_ONLY_TOOLS + submit_review, NO bash, NO write_file
- `_is_qa_command_allowed()` — prefix allowlist for QA bash commands
- `make_qa_handlers()` — QA bash enforces allowlist before policy engine
- `make_reviewer_handlers()` — no bash or write handlers at all

### Event Bus (`backend/app/event_bus/`)
- `models.py` — `GridironEvent` Pydantic model (frozen, UUID event_id, typed payload)
- Factory functions for all 9 core event types (doc-12 table)
- `bus.py` — `publish_event()`, `subscribe()`, `unsubscribe()`, `get_unprocessed_events()`
- Retry: 3× with exponential backoff (0.5s × 2^attempt)
- `_write_failed_event()` — dead-letter after retries exhausted
- In-memory subscriber registry (works without DB; DB persistence when session provided)
- `_persist_event()` — inserts into events table + pg_notify
- Replay: `get_unprocessed_events(task_id, since, db)` queries events > last_processed_at

### Artifact Store (`backend/app/artifacts/`)
- `store.py` — `save_artifact()`, `save_artifact_async()`, `get_artifact()`, `list_artifacts()`
- Local disk adapter: `{WORKTREES_DIR}/../artifacts/{artifact_id}`
- No hardcoded paths — storage dir derived from settings
- `ArtifactRecord` dataclass returned on save

### Dispatcher (`backend/app/pipeline/dispatcher.py`)
- Routing table: backend→backend_dev, frontend→frontend_dev, test→qa, docs→backend_dev
- `get_agent_for_type()` — pure function, no LLM needed
- `dispatch_subtask()` — routes to correct agent, returns `{files_changed, error, agent}`

### DB models + migration
- `backend/app/db/models.py` — added Event, FailedEvent, Artifact ORM classes
- `backend/migrations/versions/002_phase4_tables.py` — creates events, failed_events, artifacts tables with indexes

### API + frontend
- `backend/app/api/artifacts.py` — `GET /api/tasks/:id/artifacts`, `GET /api/artifacts/:id`
- `backend/app/main.py` — artifacts router registered

### Research notes
- `docs/research/roo-notes.md` — mode separation, tool groups, structural enforcement patterns
- `docs/research/autogen-notes.md` — message-passing decoupling, topic routing, stateless agents

### Bug fixes
- `context_builder.py` — removed unused `get_settings()` call that was failing 5 tests

## Verdict

✅ GREEN FLAG — PHASE 4 COMPLETE

- 123/123 non-pending tests pass
- 47/47 pending tests skip cleanly
- mypy --strict: 0 issues in 43 files
- All doc-07 tool matrix constraints verified structurally (not just by prompt)
- Event bus, artifact store, dispatcher, specialist agents, migration all implemented
