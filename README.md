# Gridiron Developer Department

An autonomous software engineering platform. Give it a goal — it decomposes it into tasks, runs the right specialist agents, enforces safety policy at every step, and hands you back verified, ready-to-review code.

---

## Architecture

```
apps/web/          → Next.js frontend (TypeScript)
backend/           → FastAPI + LangGraph backend (Python 3.11)
  app/
    agents/        → 27 production LangGraph agents
    api/           → FastAPI routers
    pipeline/      → LangGraph StateGraph orchestration
    policy/        → Safety policy engine (path + command guards)
    memory/        → pgvector engineering memory
    event_bus/     → In-process + Redis Streams event bus
    queue/         → Asyncio + RQ queue adapters
    artifacts/     → DB + S3 artifact storage
  roles/           → Agent system prompts (markdown)
  migrations/      → Alembic migrations
  tests/           → 934 pytest tests
```

---

## Quick Start (local dev)

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16 with pgvector extension
- (Optional) Redis 7+ for RQ queue / Redis Streams

### 1. Clone and set up Python backend

```bash
git clone https://github.com/barotb076/CRR2906
cd CRR2906/backend

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — required fields:
#   DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/gridiron
#   ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Start the frontend

```bash
cd ../apps/web
npm install
npm run dev   # runs on http://localhost:3000
```

---

## Environment Variables

All configuration is in `backend/.env.example`. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✓ | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `ANTHROPIC_API_KEY` | ✓ | Anthropic API key (unless `USE_GROQ=true`) |
| `CORS_ORIGINS` | — | Comma-separated frontend origins (default: `http://localhost:3000`) |
| `MODEL_PLANNER` | — | Model for PM/Architect (default: `claude-haiku-4-5-20251001`) |
| `MODEL_CODER` | — | Model for Coder/Review (default: `claude-sonnet-5`) |
| `VOYAGE_API_KEY` | — | Voyage AI key for semantic memory (optional) |
| `QUEUE_BACKEND` | — | `asyncio` (default) or `rq` (requires Redis) |
| `REDIS_URL` | — | Redis URL (required when `QUEUE_BACKEND=rq`) |
| `ARTIFACT_BACKEND` | — | `db` (default) or `s3` |
| `S3_BUCKET` | — | S3 bucket (required when `ARTIFACT_BACKEND=s3`) |
| `SENTRY_DSN` | — | Sentry DSN (optional) |
| `ALERT_WEBHOOK_URL` | — | Webhook for task blocked/failed alerts (optional) |

---

## Running Tests

```bash
cd backend

# Fast tests (no LLM calls) — runs in ~34 seconds
pytest tests/ -q

# Include slow LLM eval tests (requires ANTHROPIC_API_KEY or USE_GROQ=true)
pytest tests/ -q -m slow

# Type checking
mypy app/ --strict --ignore-missing-imports

# Linting
ruff check .
black --check .
```

---

## Production Deployment

### Backend (Railway / Fly.io / any Docker host)

```bash
# Build
docker build -f backend/Dockerfile -t gridiron-backend .

# Run migrations before starting
docker run --env-file .env gridiron-backend alembic upgrade head

# Start
docker run -p 8000:8000 --env-file .env gridiron-backend \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Required env vars in production:** `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CORS_ORIGINS` (set to your frontend domain).

### Frontend (Vercel)

The `vercel.json` at the repo root configures the Next.js deployment:

```bash
cd apps/web
vercel --prod
# Set environment variable: NEXT_PUBLIC_API_URL=https://your-backend.example.com
```

### RQ Workers (if QUEUE_BACKEND=rq)

```bash
rq worker gridiron-high gridiron-default \
  --url $REDIS_URL \
  --with-scheduler
```

---

## The 27 Agents

### Core pipeline agents
| Agent | Purpose |
|-------|---------|
| `pm` | Product Manager — decomposes goals into epics and tasks |
| `architect` | System design and technical planning |
| `decomposer` | Task decomposition and assignment |
| `planner` | Sprint planning and story pointing |
| `coder` | Code implementation |
| `qa` | Quality assurance and testing |
| `manager` | Epic supervisor and subtask orchestration |
| `executive` | Multi-epic goal planning |
| `research` | Web search and research (read-only) |

### Specialized agents (dispatchable via API)
| Agent slug | Purpose |
|-----------|---------|
| `bug_fix` | Diagnose and fix bugs |
| `security_reviewer` | Code security review |
| `arch_reviewer` | Architecture review |
| `sql_agent` | SQL query writing and optimization |
| `docker_agent` | Dockerfile and docker-compose authoring |
| `cicd_agent` | CI/CD pipeline configuration |
| `refactor_agent` | Code refactoring |
| `readme_agent` | README and docs generation |
| `api_docs_agent` | OpenAPI docs |
| `dependency_agent` | Dependency audit and updates |
| `monitoring_agent` | Observability configuration |
| `performance_reviewer` | Performance profiling and N+1 detection |
| `style_reviewer` | Code style and linting |
| `sprint_planner` | Sprint planning and complexity estimation |
| `business_analyst` | Requirements analysis |
| `migration_agent` | Database migration authoring |
| `schema_agent` | Schema design and validation |
| `ai_engineer` | AI/ML integration |
| `cleanup_agent` | Dead code removal |
| `tech_debt_agent` | Tech debt analysis |
| `release_notes_agent` | Release notes from git log |
| `evaluation_agent` | LLM output evaluation suite |
| `rag_engineer_agent` | RAG pipeline design |
| `changelog_agent` | CHANGELOG.md maintenance |
| `user_story_generator` | Gherkin user stories |
| `security_architect` | STRIDE threat modelling (read-only) |
| `database_architect` | Schema design and index recommendations |

### Dispatch any agent

```bash
curl -X POST http://localhost:8000/api/specialized-agents/bug_fix/run-sync \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": 1,
    "description": "The login endpoint returns 500 when email contains a +",
    "repo_path": "/path/to/your/repo"
  }'
```

---

## Safety Model

Every agent operates within a policy engine that blocks:

- Writing `.env*` files
- Writing to `secrets/` directories
- Writing to `.github/workflows/`
- Running `rm -rf`, `git push`, `kubectl`, `docker push`, `vercel deploy`, `npm publish`
- Path traversal attacks (worktree boundary enforcement)

Policy is enforced in **Python code** at the tool handler level — not in the LLM prompt. An agent cannot bypass it.

Max 3 self-correction retries per task → status `blocked` → human review required.

---

## Documentation

| Document | Location |
|----------|----------|
| Add a new agent | [docs/ADD_A_NEW_AGENT.md](docs/ADD_A_NEW_AGENT.md) |
| Sellability gap analysis | [docs/SELLABILITY_GAP.md](docs/SELLABILITY_GAP.md) |
| Final audit report | [docs/reports/FINAL_AUDIT_REPORT.md](docs/reports/FINAL_AUDIT_REPORT.md) |
| Project state (live) | [PROJECT.md](PROJECT.md) |

---

## License

Proprietary — Gridiron Developer Department. All rights reserved.
