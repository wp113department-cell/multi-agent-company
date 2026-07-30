# Gridiron Developer Department

**An autonomous multi-agent software engineering platform.** Give it a goal — it decomposes it into
tasks, dispatches the right specialist agents from a fleet of 72, enforces safety policy in code at
every step, and hands you back verified, ready-to-review work.

[![License: Proprietary](https://img.shields.io/badge/license-proprietary-red.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](backend/requirements.txt)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](package.json)
[![Tests](https://img.shields.io/badge/tests-3%2C500%2B%20passing-brightgreen.svg)](backend/tests)

**Author:** Bhaskar Barot, AI/ML Engineer

---

## Table of Contents

- [Why Gridiron](#why-gridiron)
- [Architecture](#architecture)
- [Quick Start](#quick-start-local-dev)
- [Environment Variables](#environment-variables)
- [Running Tests](#running-tests)
- [Production Deployment](#production-deployment)
- [The Agent Fleet](#the-agent-fleet-72-agents)
- [Safety & Security Model](#safety--security-model)
- [Documentation](#documentation)
- [License](#license)

---

## Why Gridiron

Most "AI coding assistant" projects are a single agent with a big system prompt. Gridiron is built
differently — as a real engineering **department**: a planning pipeline (PM → Architect →
Decomposer → Manager) that dispatches work to 72 specialist agents, each with its own scoped tool
access, its own verification contract, and its own role definition — the same way a real
engineering org has a security reviewer who isn't also writing your database migrations.

What that buys you, concretely:

- **Graph-enforced verification, not model-claimed verification.** An agent can't just *say* it ran
  the tests — the orchestration graph tracks which tools actually ran and overrides a false claim
  with the real result before it ever reaches you.
- **Real command sandboxing.** The highest-risk tool calls execute inside an isolated, ephemeral,
  resource-capped container — not just a regex denylist hoping to catch every dangerous phrasing.
- **Blocking verification gates.** A declared prerequisite (e.g. "must read the file before editing
  it") can now genuinely refuse the dependent action, not just get logged after the fact.
- **Project-scoped memory.** Engineering memory (past outcomes, architecture notes, learned lessons)
  is scoped per-repository, so lessons from one codebase don't leak into another.
- **Human-gated destructive actions.** Deleting a file, overwriting existing content, or publishing
  a new "fleet-wide learning" all pause for explicit approval before they take effect — not after.
- **Dependency-aware dispatch.** Subtasks execute in real topological order, so a subtask that
  depends on a database migration never starts before that migration lands.

---

## Architecture

```
apps/web/            → Next.js frontend (TypeScript, App Router)
backend/              → FastAPI + LangGraph backend (Python 3.11+)
  app/
    agents/          → 72 production LangGraph agents (roles/*.md are their system prompts)
    api/             → 18 FastAPI routers
    pipeline/        → LangGraph StateGraph orchestration (PM → Architect → Decomposer → Manager)
    policy/          → Safety policy engine — command denylist, path guards, Docker sandbox
    fleet/           → Fleet OS: capability registry, dispatcher, metrics, audit log, self-improvement
    memory/          → pgvector engineering memory, project-scoped
    security/        → Credential vault (Fernet encryption at rest)
    event_bus/       → In-process + Redis Streams event bus
    queue/           → Asyncio + RQ queue adapters
    artifacts/       → DB + S3 artifact storage
  roles/             → Agent system prompts (markdown, one per agent)
  migrations/        → Alembic migrations
  tests/             → 3,500+ pytest tests
```

---

## Quick Start (local dev)

### Prerequisites

- Python 3.11+
- Node.js 20+ with [pnpm](https://pnpm.io/) (this is a pnpm workspace — see `pnpm-workspace.yaml`)
- PostgreSQL 16 with the `pgvector` extension
- Docker (used for sandboxed command execution — see [Safety & Security Model](#safety--security-model))
- (Optional) Redis 7+ for the RQ queue backend / Redis Streams

### 1. Clone and set up the Python backend

```bash
git clone https://github.com/wp113department-cell/multi-agent-company.git
cd multi-agent-company/backend

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — required fields:
#   DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/gridiron
#   ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Bring up Postgres (and Redis) via Docker

```bash
cd ..
docker compose up -d db          # add `redis` too if QUEUE_BACKEND=rq
```

### 4. Run database migrations

```bash
cd backend
alembic upgrade head
```

### 5. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Start the frontend

```bash
cd ..
pnpm install
pnpm --filter web dev   # runs on http://localhost:3000
```

---

## Environment Variables

Full reference in `backend/.env.example`. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✓ | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `ANTHROPIC_API_KEY` | ✓ | Anthropic API key (unless `USE_GROQ=true`) |
| `DEPLOYMENT_ENV` | — | `development` (default) \| `staging` \| `production`. `production` hard-requires `CREDENTIAL_ENCRYPTION_KEY`. |
| `CREDENTIAL_ENCRYPTION_KEY` | — | Fernet key encrypting stored credentials at rest. Required when `DEPLOYMENT_ENV=production`. |
| `BASH_SANDBOX_ENABLED` | — | `true` (default) — routes the highest-risk bash tools through an isolated Docker container. Explicit opt-out only. |
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

# Full suite — 3,500+ tests
pytest tests/ -q

# Include slow LLM eval tests (requires ANTHROPIC_API_KEY or USE_GROQ=true)
pytest tests/ -q -m slow

# Type checking (strict)
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

**Required env vars in production:** `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CORS_ORIGINS` (your
frontend domain), `DEPLOYMENT_ENV=production`, `CREDENTIAL_ENCRYPTION_KEY`.

### Frontend (Vercel)

The `vercel.json` at the repo root configures the Next.js deployment:

```bash
cd apps/web
vercel --prod
# Set environment variable: NEXT_PUBLIC_API_URL=https://your-backend.example.com
```

### RQ Workers (if `QUEUE_BACKEND=rq`)

```bash
rq worker gridiron-high gridiron-default \
  --url $REDIS_URL \
  --with-scheduler
```

---

## The Agent Fleet (72 agents)

Every agent below declares its own `AGENT_CONTRACT` — allowed tools, risk level, and a real,
graph-enforced verification contract — and has a corresponding system prompt in `backend/roles/`.

### Core Pipeline

| Agent | Purpose |
|-------|---------|
| `pm` | Translates a task description into goals, constraints, and acceptance criteria |
| `architect` | Reads the PM brief + codebase to produce a technical plan with impacted files and risks |
| `decomposer` | Breaks the architect's plan into typed, ordered subtasks with a dependency graph |
| `planner` | Reads the codebase and produces a validated markdown implementation plan |
| `executive` | Converts a plain-language goal into structured epics and a business summary |
| `manager` | Orchestrates the full Dev → QA → Review pipeline per subtask; manages epic lifecycle |
| `coder` | Implements an approved plan in a git worktree — generic backend/frontend capable |
| `backend_dev` | Implements server-side changes in an isolated worktree (Python/FastAPI) |
| `frontend_dev` | Implements TypeScript/Next.js UI changes in an isolated worktree |
| `qa` | Runs pytest, mypy, and ruff in a worktree — test commands only, no writes |
| `reviewer` | Reads diffs and codebase context to produce structured code-review findings |
| `chat_agent` | Interactive streaming chat agent — full agentic loop over the repo |
| `research` | Reads repo files and searches the web to gather technical context |
| `docs` | Writes changelog and README updates to a worktree after epic implementation |

### Code Quality & Review

| Agent | Purpose |
|-------|---------|
| `code_quality_agent` | Reviews code for quality, maintainability, complexity, and style issues |
| `style_reviewer` | Enforces code style via linter, naming conventions, and import hygiene (read-only) |
| `architecture_reviewer` | Reviews import graphs, circular dependencies, dead code, layer violations |
| `performance_reviewer` | Finds slow SQL queries, O(n) loops, missing indexes |
| `tech_debt_agent` | Audits lint violations, test coverage gaps, oversized functions |
| `refactor_agent` | Refactors code while verifying behavior is preserved via test runs before/after |
| `cleanup_agent` | Removes dead code, organizes imports, deletes unused files (scan-before-delete) |
| `debugger_agent` | Diagnoses bugs, traces root causes, produces concrete fix recommendations |
| `bug_fix` | Diagnoses and fixes bugs with verified test coverage |
| `code_explainer_agent` | Produces plain-English explanations of source code at varying detail levels |

### Security & Compliance

| Agent | Purpose |
|-------|---------|
| `security_reviewer` | Read-only security audit: secrets scan, SQL injection, auth, config vulnerabilities |
| `security_architect` | STRIDE threat modelling and OWASP Top 10 review (read-only) |
| `compliance_agent` | Audits for regulatory compliance (GDPR, SOC2, HIPAA, PCI-DSS) |
| `dependency_security_agent` | Scans dependencies for known CVEs via **live** `pip-audit`/`npm audit` runs |
| `env_checker_agent` | Finds undocumented env vars, hardcoded secrets, missing `.env.example` entries |

### Testing & QA

| Agent | Purpose |
|-------|---------|
| `test_writer_agent` | Writes pytest/Jest test suites from actual source code and existing tests |
| `test_coverage_agent` | Analyzes coverage reports to identify specific untested code paths |
| `evaluation_agent` | Runs LLM output evaluation suites, scores test cases |
| `load_test_agent` | Generates k6/Locust load test scripts from real routes and schemas |

### Infrastructure & DevOps

| Agent | Purpose |
|-------|---------|
| `docker_agent` | Inspects/modifies Docker configuration — always requires human approval |
| `cicd_agent` | Manages CI/CD pipeline configuration — always requires human approval |
| `infra_agent` | Reviews Terraform/K8s/Dockerfiles/CI-CD for security risks and missing resource limits |
| `devops` | Runs allowlisted health-check commands and reports system status (no deploy, no writes) |
| `monitoring_agent` | Collects real system metrics and health status from live tools (read-only) |
| `incident_responder_agent` | Triages incidents, identifies blast radius, produces executable mitigations |
| `rollback_agent` | Generates rollback plans from git log and migration history |
| `runbook_generator_agent` | Writes operational runbooks from actual service code and deploy config |
| `slo_agent` | Defines Service Level Objectives from existing monitoring config |

### Database & Data

| Agent | Purpose |
|-------|---------|
| `database_architect` | Schema design, normalization, index recommendations, DDL generation |
| `schema_agent` | Inspects and designs database schemas |
| `sql_agent` | Writes and validates SQL queries/migrations against the live schema |
| `migration_agent` | Writes and validates Alembic migrations with schema inspection first |
| `data_pipeline_agent` | Designs, reviews, and documents data pipelines and ETL flows |
| `rag_engineer_agent` | Designs RAG pipelines: chunking strategy, embedding model selection, vector store |

### Documentation & Communication

| Agent | Purpose |
|-------|---------|
| `readme_agent` | Writes README/documentation from real codebase inspection |
| `api_docs_agent` | Documents API endpoints from actual route handlers and Pydantic schemas |
| `changelog_agent` | Maintains `CHANGELOG.md` in Keep-a-Changelog format from git history |
| `release_notes_agent` | Generates `RELEASE_NOTES.md` from git log between version tags |
| `onboarding_agent` | Generates developer onboarding docs from actual repo files |
| `user_story_generator` | Generates structured user stories with Gherkin acceptance criteria |
| `business_analyst` | Derives user stories, acceptance criteria, and edge cases |

### Planning & Estimation

| Agent | Purpose |
|-------|---------|
| `sprint_planner` | Breaks features into sprint-ready stories with complexity estimates |
| `cost_estimator_agent` | Estimates implementation effort and LLM token costs for tasks |
| `spike_agent` | Conducts a time-boxed research spike on a specific technical question |

### Fleet Self-Governance

Meta-agents that monitor and improve the fleet itself — a closed-loop self-improvement subsystem
gated by human approval before any change lands.

| Agent | Purpose |
|-------|---------|
| `agent_advisor` | Reviews orchestration correctness — did the right agent(s) run for a task |
| `agent_debugger` | Detects failing agents and platform bugs from real audit-trail/metrics evidence |
| `agent_performance_reviewer` | Reviews real runtime performance data across the whole fleet |
| `quality_auditor` | Audits the platform for security risk, UI quality, and general project quality |
| `knowledge_curator` | Curates the fleet's persistent engineering memory — dedupes, recategorizes, promotes |

### Developer Experience & Specialized

| Agent | Purpose |
|-------|---------|
| `devex_agent` | Audits setup friction, missing tooling, confusing workflows |
| `accessibility_agent` | Audits frontend/UI code for WCAG 2.1 accessibility issues |
| `pair_programmer_agent` | Reads a code area, explains its current state, then guides implementation |
| `localization_agent` | Finds hardcoded user-visible strings, date/number formatting issues |
| `feature_flag_agent` | Identifies stale flags and flags with unclear ownership |
| `api_designer_agent` | Designs REST/GraphQL API contracts, schemas, and OpenAPI specs |
| `version_manager_agent` | Audits dependency versions for outdated or vulnerable packages |
| `ai_engineer` | Implements AI/ML integrations: training pipelines, inference code, eval scripts |
| `dependency_agent` | Audits dependencies for outdated versions using live registry checks |

### Dispatch any agent directly

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

## Safety & Security Model

Safety is enforced in **Python code** at the tool-handler level — never in the LLM prompt alone. An
agent cannot bypass any of the following by rephrasing its request.

- **Command denylist** — blocks `rm -rf`, `git push`, `kubectl`, `docker push`, `vercel deploy`,
  `npm publish`, fork bombs, credential-file reads, curl-pipe-to-shell, and more, with normalization
  to close common bypass variants (`rm -fr`, `--recursive --force`, etc.).
- **Docker sandbox** — the highest-risk, denylist-only bash tools execute inside a fresh, `--rm`
  container: only the target repo's own worktree is mounted, no `docker.sock` exposure, real
  cgroup-enforced memory/CPU/PID caps. Fails **closed** — if Docker is unreachable, the command is
  refused, never silently run unsandboxed.
- **Blocking verification gates** — a declared prerequisite (e.g. "must audit before claiming a
  CVE") is now a real, enforced refusal: the dependent tool call is denied before it ever executes,
  not just flagged afterward.
- **Path guards** — blocks writes to `.env*`, `secrets/`, `.github/workflows/`, and any path outside
  the agent's assigned git worktree (path-traversal protection).
- **Human-in-the-loop gates** — deleting a file, overwriting existing file content, and promoting a
  fleet-wide "learned lesson" from draft to published all pause for explicit human approval before
  taking effect.
- **Credential encryption at rest** — stored credentials are Fernet-encrypted; production deployments
  (`DEPLOYMENT_ENV=production`) hard-fail at startup if no encryption key is configured.
- **Project-scoped memory** — engineering memory is scoped per repository, so lessons learned on one
  codebase never bleed into another project's agent context.
- **Graph-enforced result verification** — at the moment an agent submits its result, the graph
  overrides any field a `VerificationConfig` tracks with what actually happened during the run,
  discarding the model's own unverified claim.
- **Bounded retries** — max 3 self-correction retries per task → status `blocked` → human review
  required.

---

## Documentation

| Document | Location |
|----------|----------|
| Add a new agent | [docs/ADD_A_NEW_AGENT.md](docs/ADD_A_NEW_AGENT.md) |
| Codebase map | [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md) |
| Architecture graphs | [docs/ARCHITECTURE_GRAPHS.md](docs/ARCHITECTURE_GRAPHS.md) |
| Deployment guide | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Sellability gap analysis | [docs/SELLABILITY_GAP.md](docs/SELLABILITY_GAP.md) |
| Build plan completion | [docs/BUILD_PLAN_COMPLETION.md](docs/BUILD_PLAN_COMPLETION.md) |
| Final audit report | [docs/reports/FINAL_AUDIT_REPORT.md](docs/reports/FINAL_AUDIT_REPORT.md) |
| Production-readiness audit (120 questions) | [answers.md](answers.md) |
| Engineering change log | [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) |
| Project state (live) | [PROJECT.md](PROJECT.md) |

---

## License

**Proprietary — All Rights Reserved.** Copyright (c) 2026 Bhaskar Barot, AI/ML Engineer.

This codebase is not open source. Copying, redistribution, modification, or use of any part of this
software without prior express written permission from the copyright holder is strictly prohibited.
See [LICENSE](LICENSE) for the full terms.
