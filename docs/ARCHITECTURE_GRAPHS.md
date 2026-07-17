# Architecture Graphs — Gridiron Developer Department
_Auto-generated 2026-07-17. Source of truth: `backend/app/`. Re-run analysis to update._

---

## 1. System Layer Map

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser / Next.js Frontend (apps/web/ — TypeScript)            │
│  Pages: /tasks · /repo · /epics · /goals · /chat · /settings   │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/SSE  (port 8000)
┌────────────────────────────▼────────────────────────────────────┐
│  FastAPI  (backend/app/main.py)                                  │
│  12 routers — JWT auth (Bearer token)                            │
└──┬──────────┬─────────┬─────────┬──────────┬────────────────────┘
   │          │         │         │          │
   ▼          ▼         ▼         ▼          ▼
 Tasks     Auth      Epics    Chat SSE   Registry
 Repo     Goals    Metrics   Memory    Specialized
 Artifacts Settings                     Agents
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  LangGraph Orchestration Layer                                    │
│  ┌───────────────────────┐   ┌──────────────────────────────┐   │
│  │ Pipeline Graph        │   │ Agent Graph (run_agent_graph) │   │
│  │ pm → architect →      │   │ planner_node → memory_hook → │   │
│  │ decomposer →          │   │ call_llm ⇄ execute_tools     │   │
│  │ human_review → END    │   │ → reflection → lesson        │   │
│  └───────────────────────┘   └──────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Fleet OS (backend/app/fleet/)                                   │
│  capability_registry · agent_registry · fleet_checkpoint         │
│  fleet_events (8 typed events) · audit_log · metrics             │
│  tool_manifest · fleet_manager                                   │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Data Layer                                                      │
│  PostgreSQL (asyncpg) — 21 ORM models                            │
│  pgvector — memory_embeddings (Voyage AI)                        │
│  Redis (RQ) — background job queue                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Pipeline Graph (Tasks flow)

```
START
  │
  ▼
┌─────┐     POST /tasks/{id}/run triggers this graph
│ pm  │  ← PM Agent: task → goals + constraints + acceptance criteria
└──┬──┘
   │ pm_brief
   ▼
┌──────────┐
│ architect│  ← Architect Agent: pm_brief → architect_plan + impacted_files
└────┬─────┘
     │ architect_plan
     ▼
┌───────────┐
│ decomposer│  ← Decomposer Agent: plan → typed subtasks with deps
└─────┬─────┘
      │ subtasks
      ▼
┌─────────────┐
│ human_review│  ← Pause: POST /tasks/{id}/approve or /reject
└─────┬───────┘
      │ approved
      ▼
     END
```

---

## 3. Agent Graph (run_agent_graph — every agent uses this)

Fleet OS flags: `enable_planning`, `enable_memory`, `enable_reflection`, `enable_lesson`

```
                    enable_planning=True?
                          │
                    ┌─────▼──────────┐
                    │  planner_node  │  Haiku: analyze task → tool strategy
                    └─────┬──────────┘
                          │
                    enable_memory=True?
                          │
                    ┌─────▼─────────────┐
                    │  memory_hook_node │  Haiku: inject relevant lessons
                    └─────┬─────────────┘
                          │
               ┌──────────▼──────────┐
               │     call_llm        │  Main model: Sonnet / Opus
               └──────────┬──────────┘
                          │
              ┌───────────▼────────────┐
              │   tool_call in reply?  │
              └──┬─────────────────────┘
                 │ yes                  │ no / STOP
                 ▼                      ▼
     ┌───────────────────┐           END (done)
     │   execute_tools   │
     └───────────┬───────┘
                 │
     enable_reflection=True?
                 │
     ┌───────────▼────────────┐
     │    reflection_node     │  Haiku: was that tool use correct?
     └───────────┬────────────┘
                 │
     enable_lesson=True? (on final turn)
                 │
     ┌───────────▼──────────┐
     │     lesson_node      │  Haiku: extract reusable lesson → memory
     └───────────┬──────────┘
                 │
                 └─────────────────► call_llm (loop)
```

VerificationConfig enforces: tools must be called and state keys set before `result` is accepted.

---

## 4. API Route Map

### /api/tasks
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tasks` | Create task |
| GET | `/api/tasks` | List tasks |
| GET | `/api/tasks/{id}` | Get task |
| PATCH | `/api/tasks/{id}` | Update task |
| POST | `/api/tasks/{id}/run` | Start pipeline |
| POST | `/api/tasks/{id}/approve` | Approve task result |
| POST | `/api/tasks/{id}/reject` | Reject task result |
| POST | `/api/tasks/{id}/pipeline/approve` | Approve pipeline stage |
| POST | `/api/tasks/{id}/pipeline/reject` | Reject pipeline stage |
| GET | `/api/tasks/{id}/subtasks` | List subtasks |
| GET | `/api/tasks/{id}/pipeline` | Get pipeline state |
| GET | `/api/tasks/{id}/diff` | Get git diff |
| POST | `/api/tasks/{id}/logs` | Append task log |
| GET | `/api/tasks/{id}/logs` | Get task logs |

### /api/auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login → JWT token |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/setup` | First-time admin setup |

### /api/repo
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/repo` | List repos |
| POST | `/api/repo/clone` | Clone + index repo |
| POST | `/api/repo/{id}/activate` | Set active repo |
| POST | `/api/repo/reindex` | Re-index active repo |
| GET | `/api/repo/reindex` | Reindex status |
| GET | `/api/repo/context` | Get repo context for agents |

### /api/epics
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/epics` | Create epic |
| GET | `/api/epics` | List epics |
| GET | `/api/epics/{id}` | Get epic |
| POST | `/api/epics/{id}/approve` | Approve epic |
| POST | `/api/epics/{id}/reject` | Reject epic |
| POST | `/api/epics/{id}/approve-cost` | Approve cost gate |
| POST | `/api/epics/{id}/policy-approval` | Policy gate approval |
| GET | `/api/epics/batch-review` | Bulk review queue |

### /api/goals
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/goals` | Create goal |
| GET | `/api/goals` | List goals |
| GET | `/api/goals/{id}` | Get goal |

### /api/chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat/sessions` | Create chat session |
| POST | `/api/chat/sessions/{id}/messages` | Send message (SSE stream) |
| POST | `/api/chat/sessions/{id}/confirm` | Confirm tool action |
| GET | `/api/chat/sessions/{id}/history` | Get chat history |
| DELETE | `/api/chat/sessions/{id}` | Delete session |

### /api/registry
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/registry` | List registered agents |
| GET | `/api/registry/{name}` | Get agent contract |
| GET | `/api/registry/{name}/metrics` | Agent run metrics |
| POST | `/api/registry` | Register agent (internal) |

### /api/memory
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory/patterns` | List learned patterns |
| GET | `/api/memory/search` | Semantic search over lessons |

### /api/metrics
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/metrics` | System metrics |
| GET | `/api/metrics/epics` | Epic cost summary |

### /api/settings
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Get settings |
| POST | `/api/settings/api-key` | Set API key |
| DELETE | `/api/settings/api-key` | Clear API key |

### /api/artifacts + /api/agents (specialized)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks/{id}/artifacts` | List task artifacts |
| GET | `/api/artifacts/{id}` | Get artifact |
| GET | `/api/agents` | List specialized agents |
| POST | `/api/{name}/run` | Run agent async |
| POST | `/api/{name}/run-sync` | Run agent sync |

---

## 5. Database Model Graph

```
dev_tasks ──────────────────────────┐
  │ id, title, description,         │
  │ status, agent, cost_usd         │
  │                                 │
  ├──► task_logs (task_id FK)       │
  │      event, message, ts         │
  │                                 │
  ├──► agent_runs (task_id FK)      │
  │      agent_name, model,         │
  │      tokens_in, tokens_out      │
  │                                 │
  ├──► subtasks (task_id FK)        │
  │      type, title, status,       │
  │      files_to_edit              │
  │                                 │
  ├──► pipeline_state (task_id FK)  │
  │      stage, pm_brief,           │
  │      architect_plan, subtasks   │
  │                                 │
  └──► artifacts (task_id FK)       │
         type, path, content        │
                                    │
epics ──────────────────────────────┘
  │ goal_id FK → goals
  │ policy_id FK → policies
  ├──► policy_approvals (epic_id FK)
  └──► [links to dev_tasks via epic_id]

goals (standalone — executive agent target)
  id, title, description, status

repos
  id, name, url, local_path, is_active, indexed_at

indexed_files (repo_id FK → repos)
  ├──► symbols (file_id FK)
  └──► call_edges (caller_id + callee_id FK → symbols)

memory_embeddings
  content, embedding (pgvector), agent_name, task_id

events / failed_events
  type, payload, created_at, retry_count

user_roles
  user_id, role (admin | viewer | agent)

agents
  name, state (IDLE | RUNNING | SLEEP | BLOCKED), last_task_id

system_settings
  key, value (encrypted API keys etc.)
```

---

## 6. Fleet OS Component Graph

```
┌─────────────────────────────────────────────────────────────┐
│  Fleet OS  (backend/app/fleet/)                              │
│                                                              │
│  ┌──────────────────────┐   ┌──────────────────────────┐   │
│  │  capability_registry │   │    agent_registry         │   │
│  │  AgentCapability[]   │   │    AgentState machine:    │   │
│  │  24 agents registered│   │    IDLE → RUNNING →       │   │
│  │  .register() .all()  │   │    SLEEP | BLOCKED        │   │
│  └──────────────────────┘   └──────────────────────────┘   │
│                                                              │
│  ┌──────────────────────┐   ┌──────────────────────────┐   │
│  │   fleet_checkpoint   │   │      fleet_events         │   │
│  │  save/restore/       │   │  8 typed events:          │   │
│  │  rollback            │   │  TaskCreated              │   │
│  │  + trace_id in meta  │   │  TaskStarted              │   │
│  └──────────────────────┘   │  TaskCompleted            │   │
│                              │  TaskFailed               │   │
│  ┌──────────────────────┐   │  ReviewRequested          │   │
│  │     audit_log        │   │  LessonPublished          │   │
│  │  every agent action  │   │  HealthUpdated            │   │
│  │  + trace_id          │   │  MemoryCreated            │   │
│  └──────────────────────┘   └──────────────────────────┘   │
│                                                              │
│  ┌──────────────────────┐   ┌──────────────────────────┐   │
│  │    fleet_manager     │   │    tool_manifest          │   │
│  │  orchestrate agents  │   │  tool name → handler map  │   │
│  │  capacity/routing    │   │  for 36 chat tools        │   │
│  └──────────────────────┘   └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Config / Env Var Map

All env vars read through `backend/app/config.py` (Pydantic BaseSettings).

| Category | Key Env Vars |
|----------|-------------|
| Database | `DATABASE_URL` |
| LLM | `ANTHROPIC_API_KEY`, `MODEL_PLANNER`, `MODEL_CODER`, `MODEL_ROUTER` |
| Embeddings | `VOYAGE_API_KEY`, `VOYAGE_MODEL`, `VOYAGE_DIMENSIONS` |
| Repo | `TARGET_REPO_PATH`, `WORKTREES_DIR`, `REPOS_DIR` |
| Pipeline | `PIPELINE_MODE`, `MAX_RETRIES`, `CONTEXT_TOKEN_BUDGET` |
| Cost gates | `COST_THRESHOLD_WARN_USD`, `COST_THRESHOLD_BLOCK_USD` |
| Manager | `MANAGER_MAX_CONCURRENT_TASKS`, `MANAGER_HEARTBEAT_INTERVAL_S` |
| Security | `DEVOPS_BASH_ALLOWLIST`, `RBAC_ENABLED` |
| Features | `RESEARCH_ENABLED`, `MEMORY_ENABLED`, `MEMORY_TOP_K` |
| Concurrency | `MAX_CONCURRENT_AGENTS`, `AGENT_TIMEOUT_S` |
| Epic | `EXECUTIVE_MAX_EPICS_PER_GOAL` |
| Queue | `QUEUE_BACKEND`, `REDIS_URL`, `REDIS_QUEUE_NAME` |
| Artifacts | `ARTIFACT_STORAGE_BACKEND`, `ARTIFACT_LOCAL_DIR` |

Missing required env at startup → `ValidationError` with clear message. No silent defaults for secrets.

---

## 8. Agent → Tool → Model Tier Map

| Agent | Model Tier | Risk | Key Tools |
|-------|-----------|------|-----------|
| pm, planner, decomposer, architect | `MODEL_PLANNER` (Sonnet) | low | read_file, submit_* |
| coder, backend_dev, frontend_dev, bug_fix, refactor_agent | `MODEL_CODER` (Sonnet) | medium | edit_file, bash, git_diff |
| reviewer, qa, devops | `MODEL_CODER` (Sonnet) | low–medium | bash, git_diff |
| docker_agent, cicd_agent | `MODEL_CODER` (Sonnet) | high | docker_build, bash |
| research | `MODEL_ROUTER` (Haiku) | low | read_file, search_code |
| executive | `MODEL_PLANNER` (Sonnet→Opus via env) | low | none (pure LLM) |
| security_reviewer, architecture_reviewer | `MODEL_CODER` (Sonnet) | low | import_graph, secrets_scan |
| sql_agent | `MODEL_CODER` (Sonnet) | medium | inspect_schema, sql_query |
| monitoring_agent | `MODEL_ROUTER` (Haiku) | low | cpu_usage, metrics |
| readme_agent, api_docs_agent, dependency_agent | `MODEL_CODER` (Sonnet) | low | read_file, write_file |
| planner_node / memory_hook / reflection_node | `MODEL_ROUTER` (Haiku) | — | Fleet OS internal |
