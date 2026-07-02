# Pending Tests — Require API Keys

All tests in this folder are **skipped** until the matching environment variable is set.

| File | Requires | What it tests |
|---|---|---|
| `test_pm_agent.py` | `ANTHROPIC_API_KEY` | PM Agent produces a valid brief via real Claude call |
| `test_architect_agent.py` | `ANTHROPIC_API_KEY` | Architect Agent reads repo + submits structured plan |
| `test_decomposer_agent.py` | `ANTHROPIC_API_KEY` | Decomposer Agent produces typed subtask list |
| `test_planner_agent.py` | `ANTHROPIC_API_KEY` | Planner Agent produces validated markdown plan, retries on bad output |
| `test_coder_agent.py` | `ANTHROPIC_API_KEY` | Coder Agent writes a file in a worktree, passes mypy+ruff |
| `test_pipeline_e2e.py` | `ANTHROPIC_API_KEY` | Full PM → Architect → Decomposer LangGraph run |
| `test_embeddings.py` | `VOYAGE_API_KEY` | Voyage AI embedding generation + semantic search |
| `test_db_integration.py` | `DATABASE_URL` (real PG) | Full CRUD: tasks, logs, agent_runs, subtasks |
| `test_api_e2e.py` | `ANTHROPIC_API_KEY` + `DATABASE_URL` | POST /tasks → /run → /pipeline → /approve → /diff |

## How to run once you have the keys

```bash
# Add to backend/.env:
ANTHROPIC_API_KEY=sk-ant-your-key
DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost:5432/gridiron_dev
VOYAGE_API_KEY=pa-your-voyage-key   # optional — enables semantic search

# Run all pending tests:
cd backend
.venv/bin/pytest tests/pending/ -v

# Run just the agent tests:
.venv/bin/pytest tests/pending/ -v -k "agent"

# Run just the pipeline E2E:
.venv/bin/pytest tests/pending/test_pipeline_e2e.py -v
```
