# Gridiron Developer Department — How It Works

## What Is This Project?

Gridiron Developer Department is a self-hosted AI-powered software engineering platform. You connect it to a code repository, describe a task in plain English, and a fleet of 68 specialized AI agents plan, write, and review the code for you. Everything runs on your machine — no cloud SaaS, no shared data.

---

## High-Level Architecture

```
Browser (Next.js)
      │
      ▼
FastAPI Backend (Python)
      │
      ├── LangGraph Pipelines  ── 68 AI Agents (Anthropic Claude / Groq)
      │
      ├── PostgreSQL Database
      │
      └── Your Code Repository (cloned locally)
```

**Frontend**: Next.js 14 (TypeScript) at `apps/web/`. Talks to the backend over HTTP via Next.js rewrites (`/api/*` → `http://localhost:8000/api/*`).

**Backend**: Python FastAPI at `backend/`. Runs the agents, manages state, serves the REST API.

**LLM**: Either Anthropic Claude (production) or Groq (testing/free tier). Switched via `USE_GROQ=true/false` in `.env`.

---

## The Fleet: 68 AI Agents

Every agent is a Python module in `backend/app/agents/`. Each one has:

| Component | Where it lives |
|---|---|
| Python class + tools | `backend/app/agents/<name>.py` |
| System prompt (role) | `backend/roles/<name>.md` |
| Pydantic output schema | inside the `.py` file (`AGENT_CONTRACT`) |
| LangGraph graph runner | `backend/app/agents/base_graph.py` |

Agents are grouped by responsibility:

| Category | Examples |
|---|---|
| **Planning** | PM (`pm.py`), Architect (`architect.py`), Decomposer (`decomposer.py`), Planner (`planner.py`) |
| **Coding** | Coder (`coder.py`), Backend Dev, Frontend Dev, Bug Fix, Refactor, Migration |
| **Review** | Reviewer, Code Quality, Security Reviewer, Architecture Reviewer, Performance Reviewer |
| **DevOps** | Docker Agent, CICD Agent, DevOps, Infra Agent |
| **Analysis** | Debugger, Code Explainer, Cost Estimator, Business Analyst |
| **Specialist** | Accessibility, Compliance, Localization, SLO, Spike, Runbook Generator |
| **Meta** | PM (epic-level), Manager, Executive, Research Agent |

---

## How a Task Flows Through the System

### Step 1 — Create a Task

User creates a task in the Repository → Tasks tab, giving it a title, description, and (optionally) a target repository.

The task is saved to `dev_tasks` in PostgreSQL with `status = "pending"`.

### Step 2 — Run the Planning Pipeline

User clicks **Run Planning Pipeline**. This triggers `POST /api/tasks/{id}/run` with `mode=full`.

The pipeline runs 3 agents in sequence:

```
PM Agent → Architect Agent → Decomposer Agent
```

Each is a LangGraph `StateGraph` node:

1. **PM Agent** — reads the task description, calls tools to gather context, writes a structured brief (goals, constraints, acceptance criteria).
2. **Architect Agent** — reads the PM brief, proposes a technical architecture (files to touch, approach, risk areas).
3. **Decomposer Agent** — breaks the architect plan into concrete subtasks with estimated complexity.

The pipeline state is saved to `pipeline_state`. The task moves through statuses: `pending → planning → awaiting_approval`.

### Step 3 — Human Approves the Plan

The plan appears in the task detail page. User clicks **Approve Plan & Start Coding** (or Reject to restart).

### Step 4 — Coding

After approval, the Coder Agent runs. It:
- Reads the repository context (file tree, relevant symbols)
- Calls tools to read files, write diffs, verify changes
- Produces a unified diff of proposed changes

Task status moves to `coding → ready_for_review`.

### Step 5 — Diff Review

The diff appears in the UI. User clicks **Approve & Complete** to accept or **Reject** to send back.

On approval, `status = "completed"`. The changes were made inside a git worktree (isolated copy) — the user applies them manually.

### Restart

If a task ends up in `error`, `failed`, or `blocked` status, the **↺ Restart Pipeline** button resets it to `pending` and re-triggers the full planning pipeline in one click.

---

## How Agents Actually Work

Every agent call flows through `backend/app/agents/base.py`:

```python
run_agent(role_name, model, messages, tools, tool_handlers, max_turns)
```

1. Loads the system prompt from `backend/roles/<role_name>.md`
2. Calls the Anthropic SDK (or Groq SDK if `USE_GROQ=true`) in a loop
3. If the model calls a tool, the matching `tool_handler` function runs
4. Continues until the agent calls the `submit` tool (submitting its result) or hits `max_turns`
5. Returns `(text, tokens_in, tokens_out, cache_read_tokens, cache_creation_tokens)`

For LangGraph-based agents, `base_graph.py` wraps this into a `StateGraph` with:
- A `VerificationConfig` (what the agent must return in its result)
- Planning, memory, and reflection steps (optional, per agent)
- A lesson-extraction step on failure

---

## Repository Intelligence

When an agent needs to understand the codebase:

1. `backend/app/repo_tools/scanner.py` — walks the active repo, parses Python/TS/JS with AST, builds a file index with symbols and call edges
2. `backend/app/repo_tools/context_builder.py` — given a task description, finds the most relevant files and symbols via keyword matching
3. The context is injected into the agent's messages before it starts planning

---

## The Database

PostgreSQL (local, port 5432). 16 tables:

| Table | Purpose |
|---|---|
| `dev_tasks` | Tasks with status, plan, diff, logs |
| `task_logs` | Timestamped log lines per task (category + message) |
| `agent_runs` | Token counts, model, duration for every agent call |
| `pipeline_state` | PM/Architect/Decomposer output per task |
| `subtasks` | Decomposer output — individual work items |
| `artifacts` | Structured outputs (plans, diffs, reports) stored as files |
| `epics` | Collections of related tasks with cost tracking |
| `goals` | High-level objectives that generate epics |
| `repos` | Cloned GitHub repositories + active repo tracking |
| `agents` | Fleet registry — 68 registered agents with capability tags |
| `policies` | Policy rules (what agents are allowed to do) |
| `policy_approvals` | Audit log of policy checks |
| `user_roles` | RBAC — who can do what |
| `system_settings` | Runtime settings (API keys, feature flags) |
| `indexed_files` | Repo file index for code search |
| `memory_embeddings` | Semantic memory for agents (Voyage AI embeddings) |

Migrations managed by Alembic (`backend/migrations/`). 7 migrations applied (001–007).

---

## LLM Backends and Model Tiers

The system uses 3 model tiers, configured in `.env`:

| Tier | Env Var | Use Case | Default (Groq) |
|---|---|---|---|
| Router/Haiku | `GROQ_MODEL_ROUTER` | Triage, routing, heartbeat | `llama-3.1-8b-instant` |
| Planner/Sonnet | `GROQ_MODEL_PLANNER` | Architecture, PM, decomposition | `llama-3.3-70b-versatile` |
| Coder/Sonnet | `GROQ_MODEL_CODER` | Code writing, review, analysis | `llama-3.3-70b-versatile` |

Switch from Groq → Anthropic by setting `USE_GROQ=false` and filling in `ANTHROPIC_API_KEY`.

---

## Cost Tracking (KPIs)

Every agent call is logged in `agent_runs` with token counts. The KPIs page (`/metrics`) shows:

- **Total estimated spend** — blended at ~$2.5/M input, ~$12/M output
- **Cache savings** — tokens served from the prompt cache at ~$0.25/M instead of full price
- **Per-agent breakdown** — which agents ran most and cost most
- **Per-epic cost** — estimated and actual spend per project epic

---

## Security Model

- **No agent writes to `.env` files, secrets, or CI/CD pipelines** — enforced in `backend/app/policy/engine.py`
- **All code changes happen in git worktrees** — isolated from the working copy until human approval
- **Max 3 self-correction retries** — then the task moves to `blocked` and logs are preserved for review
- **RBAC** — role-based access control (`user_roles` table, `RBAC_ENABLED=true` in `.env`)
- **JWT auth** — `JWT_AUTH_ENABLED=true`, tokens expire after 24 hours

---

## Frontend Pages

| Route | What it shows |
|---|---|
| `/repo` | Connect and manage GitHub repositories |
| `/tasks` | All tasks — create, filter by status/repo, open detail |
| `/tasks/[id]` | Task detail: run pipeline, approve plan, review diff, see logs |
| `/epics` | Epic tracking — groups of related tasks |
| `/goals` | High-level goals that auto-generate epics |
| `/metrics` | KPIs: cost, performance, agent breakdown, per-epic cost |
| `/settings` | API key management (Anthropic + OpenAI), model config |

---

## How to Run It

```bash
# Backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend
cd apps/web
npm run dev
```

Open `http://localhost:3000`. Log in → go to Repository tab → clone a repo → create a task → run the pipeline.

---

## Project Stats (as of 2026-07-20)

- **68 agents** with full AGENT_CONTRACT, VerificationConfig, and role prompts
- **2260 tests** passing (pytest)
- **7 phases** complete: Core API → Epics/Cost/RBAC → Agent Registry/Research/Memory → Fleet enhancements (Days 1–6)
- **Karpathy engineering principles** applied to 60+ agent role files
