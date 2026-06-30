# 02 — System Architecture Blueprint

**Applies from:** Stage 0 (grows through Stage 7)
**Related:** `03_Technical_Execution_Roadmap.md`, `05_Architecture_Decision_Records.md`, `09_Database_Design_Specification.md`

---

## Confirmed Technology Stack

| Layer | Technology | Reasoning (full detail in `05`) |
|---|---|---|
| AI Model / Reasoning | Claude API via the Claude Agent SDK | Ships with subagents, isolated git worktrees, permission hooks, and sandboxing built in |
| LLM Access Layer | Thin internal interface (`callModel()`) | Deliberate, low-cost swap point — not a full multi-model runtime |
| Multi-Agent Orchestration | LangGraph | Stateful, checkpointed, human-in-the-loop graph orchestration |
| Tool / Data Access | MCP (Model Context Protocol) | Standardized agent-to-tool connections (filesystem, git, GitHub, Postgres) |
| Relational Database | PostgreSQL (hosted via Supabase's Postgres, avoiding Supabase-specific lock-in features) | Trivially self-hostable later |
| Vector Database | pgvector (Stage 1–2) → Qdrant (Stage 3+) | Starts in the same Postgres instance, splits out when load justifies it |
| Repository Intelligence | AST-based code graph engine, exposed via MCP | See `10_Repository_Intelligence_Specification.md` |
| Object / Artifact Storage | Supabase Storage / S3-compatible | Plans, diffs, test results, reports |
| Background Jobs / Queue | Inngest (Stage 1–2) → Redis + BullMQ (Stage 7+) | Avoids standing up Redis before there's real concurrency |
| Event Bus | Postgres `LISTEN/NOTIFY` (Stage 4) → Redis Streams (Stage 7+) | See `12_Event_Bus_Specification.md` |
| Frontend | Next.js + TypeScript + Tailwind + TanStack Query | Mission Control Dashboard |
| Backend API | Next.js API routes (Stage 1) → NestJS (Stage 2+) | Starts simple, structures as services grow |
| Monitoring | Sentry | Runtime error tracking |
| Monorepo | Turborepo | Modular packages, clean future extraction boundaries |

## System Pipeline (end state, all stages complete)

```
Research Agent
     ↓
Product Manager Agent  (goals, acceptance criteria)
     ↓
Architect Agent  (impacted systems, risk, technical approach)
     ↓
Task Decomposer  (backend / frontend / test / docs subtasks)
     ↓
Developer Manager Agent  (assigns, tracks, retries)
     ↓        ↓        ↓        ↓
Backend    Frontend   QA       DevOps
Agent      Agent      Agent    Agent
     ↓        ↓        ↓        ↓
Code Review Agent
     ↓
Documentation Agent
     ↓
HUMAN APPROVAL GATE
     ↓
Merge → Deploy (with approval)
```

Every agent reads from and writes to the Repository Intelligence Service, the Task Queue, and the Event Bus; every action is logged and visible on the Mission Control Dashboard.

## Platform Layer Diagram

```
                         Mission Control (Dashboard)
                                    │
                              API Gateway
                                    │
                          Developer Runtime
        ┌────────────────────────────────────────────────────┐
        │  Task Queue   │ Event Bus   │ Artifact Store         │
        │  Policy Engine│ Cost Control│ Context Builder         │
        │  LangGraph (workflow orchestration + checkpointing)  │
        └────────────────────────────────────────────────────┘
                                    │
        ┌────────────────────────────────────────────────────┐
        │ Repository Intelligence Service (AST graph, MCP)     │
        │ Git/Worktree Runtime │ Sandbox/Docker │ MCP Tools     │
        │ Engineering Memory (vector store of past task history)│
        └────────────────────────────────────────────────────┘
                                    │
   Executive ─ Manager ─ Research ─ PM ─ Architect ─ Decomposer
                  │
   Backend ─ Frontend ─ QA ─ Review ─ Docs ─ DevOps   (tracked in Agent Registry)
                                    │
                          Thin Model Interface
                                    │
                              Claude API
```

## Platform Components Reference

Each component below has its own full specification document — this is the index, not the spec.

| Component | Spec Document | Introduced At |
|---|---|---|
| Repository Intelligence Service | `10_Repository_Intelligence_Specification.md` | Stage 3 |
| Memory (short-term + Engineering Memory) | `11_Memory_System_Specification.md` | Stage 3 / Stage 6 |
| Event Bus | `12_Event_Bus_Specification.md` | Stage 4 |
| Policy Engine | `13_Policy_Engine_Specification.md` | Stage 2 / Stage 5 |
| Scheduler / Concurrency | `14_Scheduler_Specification.md` | Stage 1 / Stage 7 |
| Agent Registry | `06_Agent_SDK_Specification.md` | Stage 6 |
| Mission Control Dashboard | `15_Mission_Control_Dashboard_Specification.md` | Stage 1, grows every stage |

## Deliberately Deferred Components

Two categories of suggested infrastructure are not part of this architecture, by deliberate decision rather than oversight:

**Full model-agnostic runtime** (a swappable adapter for Claude/GPT/Gemini/etc.) — every model call already routes through one thin interface, which is a contained future swap point. Building a full adapter layer for models with no current usage plan is not justified yet. See `05`, ADR-008.

**A generic "Agent OS" shared across future, unscoped departments** — the components above are already generic (none of them know anything specific to "developer work"), so extracting them into a formal shared platform later is a refactor, not a rewrite, once a second department is real. Designing that shared layer speculatively now means guessing requirements for departments that don't exist. See `05`, ADR-009.
