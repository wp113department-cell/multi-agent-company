# Python Backend Day 2 Test Report

**Date:** 2026-07-02
**Phase:** Python Backend Rebuild — Day 2 (Agents + Intelligence)

## What Was Built

All agent code, LangGraph pipeline, repo intelligence, MCP server, and FastAPI route wiring.

### Files Created (Day 2)

**Agents:**
- `backend/app/agents/base.py` — shared `run_agent()` loop: Anthropic SDK, role loader, policy enforcement, heartbeat every 5 tool calls, token tracking
- `backend/app/agents/tools.py` — `READ_ONLY_TOOLS` + `CODER_TOOLS` specs + handlers (`read_file`, `list_files`, `search_code`, `write_file`, `bash`, `submit_patch`)
- `backend/app/agents/pm.py` — PM Agent LangGraph node (submit_brief tool → goals/constraints/acceptance_criteria)
- `backend/app/agents/architect.py` — Architect Agent LangGraph node (submit_architect_plan tool → impacted_files/risks/risk_level)
- `backend/app/agents/decomposer.py` — Decomposer Agent LangGraph node (submit_subtasks tool → typed subtask list)
- `backend/app/agents/planner.py` — Planner Agent (read-only, plan validation: min 100 chars + markdown sections, 2-attempt retry)
- `backend/app/agents/coder.py` — Coder Agent (write tools, self-correction loop max 3 retries, runs mypy+ruff after each attempt)

**LangGraph Pipeline:**
- `backend/app/pipeline/state.py` — `PipelineState` TypedDict (task_id, pm_brief, architect_plan, subtasks, stage, error)
- `backend/app/pipeline/graph.py` — `StateGraph` with `MemorySaver` checkpointer, PM→Architect→Decomposer with conditional edge routing, `run_planning_pipeline()` async entry point

**Repo Intelligence:**
- `backend/app/repo_tools/scanner.py` — tree-sitter parser (Python + JS/TS), walks repo, extracts symbols (functions/classes/methods), imports, content hash; `index_repository()` + `build_call_graph()`
- `backend/app/repo_tools/embeddings.py` — Voyage AI embedding pipeline via `generate_embeddings()`, cosine-similarity `semantic_search()` (skips gracefully if VOYAGE_API_KEY not set)
- `backend/app/repo_tools/context_builder.py` — `build_context()`: keyword scoring + semantic search + dependency chain + call graph edges → `ContextResult`

**MCP Server:**
- `backend/app/mcp/server.py` — stdio JSON-RPC 2.0 MCP server, tools: `index_repository`, `search_symbols`, `build_context`, `query_dependencies`

**API Wiring:**
- `backend/app/api/agents.py` — `launch_planning_pipeline()`, `launch_planner()`, `launch_coder()` — all async background tasks, DB-backed state, heartbeat, log append
- `backend/app/api/tasks.py` — updated: `POST /run` triggers pipeline/planner, `POST /approve` triggers coder, added `GET /pipeline`, `GET /diff`
- `backend/app/api/repo.py` — updated: `POST/GET /reindex` (fire-and-forget scanner), `GET /context`

**Requirements updated:** `requirements.txt` now includes `tree-sitter==0.26.0`, `tree-sitter-python==0.25.0`, `tree-sitter-javascript==0.25.0`

## Tests

### What requires ANTHROPIC_API_KEY (deferred — pending API key purchase)
- Live agent runs: PM Agent, Architect Agent, Decomposer Agent, Planner Agent, Coder Agent
- LangGraph pipeline end-to-end with real Anthropic calls
- Voyage AI embeddings (requires VOYAGE_API_KEY)
- DB integration tests (require live Postgres + DATABASE_URL)

All above tests will run once API keys are in `.env`. No stubs or mocks exist in the production code path — every agent is wired to the real Anthropic SDK.

### What runs now (no API key needed)

```bash
cd backend
DATABASE_URL="..." ANTHROPIC_API_KEY="sk-ant-dummy" TARGET_REPO_PATH="." \
.venv/bin/pytest tests/ -v
```

## Results

### pytest — 63/63 PASS

| File | Tests | Result |
|---|---|---|
| tests/test_config.py | 3 | ✅ PASS |
| tests/test_context_builder.py | 5 | ✅ PASS |
| tests/test_mcp.py | 6 | ✅ PASS |
| tests/test_policy.py | 29 | ✅ PASS |
| tests/test_scanner.py | 9 | ✅ PASS |
| tests/test_status_transitions.py | 11 | ✅ PASS |

### mypy — CLEAN
```
Success: no issues found in 31 source files
```

## Scanner Coverage (9 tests)
- Finds Python + JS files ✅
- Extracts functions, classes, methods ✅
- Content hash deterministic + changes on file edit ✅
- Ignores `__pycache__`, `node_modules` etc. ✅
- Builds import-based call graph edges ✅

## Context Builder Coverage (5 tests)
- Routes file scores highest for "add endpoint to routes" task ✅
- Models file scores highest for "create task model" task ✅
- top_k budget respected ✅
- Summary contains file count ✅
- Related symbols found by keyword match ✅

## MCP Server Coverage (6 tests)
- initialize returns correct protocol version ✅
- tools/list returns all 4 tools ✅
- index_repository returns file + symbol counts ✅
- search_symbols finds known function ✅
- Unknown method → error ✅
- Unknown tool → error ✅

## Pending (API key required)
- Live agent tests (PM, Architect, Decomposer, Planner, Coder) — Phases 1–3 equivalent
- LangGraph pipeline resume test (checkpoint → kill → resume)
- Voyage AI embedding generation + semantic_search against real embeddings
- Full E2E: POST /api/tasks → POST /api/tasks/:id/run → GET /api/tasks/:id/pipeline → POST /api/tasks/:id/approve → GET /api/tasks/:id/diff

## How to Run Live Tests (once API key is available)
```bash
cp .env.example .env
# Set in .env:
# ANTHROPIC_API_KEY=sk-ant-your-key
# VOYAGE_API_KEY=pa-your-key (optional, enables semantic search)
# DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost:5432/gridiron_dev

cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
# Then test:
curl -X POST http://localhost:8000/api/tasks -H 'Content-Type: application/json' \
  -d '{"title":"Add health check endpoint","description":"Add GET /health that returns {status:ok}"}'
```

## Verdict
✅ GREEN FLAG — Python Day 2 Complete (non-API tests): 63/63 pass, mypy clean across 31 files
🔴 Live agent tests PENDING — require ANTHROPIC_API_KEY (deferred until API key purchased)
