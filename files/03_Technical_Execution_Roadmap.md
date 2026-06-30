# 03 — Technical Execution Roadmap

**Applies from:** Stage 0
**Related:** `01_Vision_Product_Requirements.md`, `02_System_Architecture_Blueprint.md`

---

## Roadmap Summary

| Stage | Focus | Team | Timeline | Cumulative |
|---|---|---|---|---|
| 0 | Repo & architecture mapping | 1 engineer | 1 week | 1 week |
| 1 | Single planning agent + task queue | 2 engineers | 6–8 weeks | ~9 weeks |
| 2 | Safe patch generation + Policy Engine v1 | 2–3 engineers | 4–6 weeks | ~15 weeks |
| 3 | Repository Intelligence Service + planning subsystem | 3–4 engineers | 9–11 weeks | ~25 weeks |
| 4 | Specialist coding agents + QA loop + Event Bus + Artifact Store | 4–5 engineers | 11–15 weeks | ~38 weeks |
| 5 | Manager Agent + Cost Controller + Policy Engine v2 | 5–6 engineers | 11–13 weeks | ~50 weeks |
| 6 | Research + Documentation agents + Agent Registry + Engineering Memory | 5–6 engineers | 5–7 weeks | ~56 weeks |
| 7 | Parallel execution + Executive Agent | 6–8 engineers + DevOps | 3–4 months, then ongoing | ~13–15 months |

**Through Stage 5 (a working, useful multi-agent department): ~11–12 months**, team growing 2→6 engineers.
**Stage 1–2 alone (one genuinely useful agent): ~3–4 months** with 2–3 engineers — independently valuable, doesn't require the rest of the roadmap to pay off.

## Stage Detail

### Stage 0 — Repository & Architecture Mapping
**Goal:** Understand the codebase before writing agent code.
**Output:** Technical architecture report (entry points, existing workers/queues, test commands, patterns to follow/avoid).
**Definition of done:** A new engineer (or agent) could read the report and navigate the real codebase confidently.

### Stage 1 — Foundation: Single Planning Agent
**Goal:** One agent reads a task, reads the repo, produces a plan. No code editing.
**Builds:** Task Queue (`dev_tasks`, `task_logs`), Agent Runtime (Claude Agent SDK, read-only tools), Mission Control v1, logging.
**Definition of done:** A human submits a task in plain English and gets back a written, accurate plan referencing real files.

### Stage 2 — Safe Code Proposal
**Goal:** The agent proposes real code changes, isolated from the main branch.
**Builds:** Worktree-isolated patch generation, diff viewer, Policy Engine v1 (PreToolUse hook), retry limits.
**Definition of done:** Agent proposes a correct, reviewable diff with zero risk to the real codebase.

### Stage 3 — Repository Intelligence Service + Planning Subsystem
**Goal:** Real codebase understanding; planning split into PM → Architect → Decomposer.
**Builds:** AST-based code graph (own MCP service), Context Builder, pgvector embeddings, LangGraph supervisor pattern with checkpointing.
**Definition of done:** Given a real feature request, the system produces an accurate goals doc, a verified (not guessed) list of impacted files, and a reviewable subtask breakdown.

### Stage 4 — Specialist Coding Agents + QA Loop
**Goal:** Multiple specialist agents implement, test, and self-correct.
**Builds:** Backend/Frontend/QA/Code Review agents, Event Bus, Artifact Store, Context Cache, shared agent template, Skills.
**Definition of done:** A medium-complexity backend task goes from subtask to clean, tested, reviewed diff with no human intervention until final approval.

### Stage 5 — Developer Manager Agent
**Goal:** One agent the human talks to; it coordinates everything below.
**Builds:** Manager Agent, Cost Controller, Policy Engine v2 (full rules engine), DevOps Agent (read-only), batched Epic Approval view.
**Definition of done:** A feature described in one sentence comes back as one clean approval screen with a cost estimate.

### Stage 6 — Research Agent + Documentation Agent + Agent Registry
**Goal:** Round out the department; start managing the growing agent fleet.
**Builds:** Research Agent, Documentation Agent, Agent Registry (capability-tagged), Engineering Memory v1.
**Definition of done:** Full pipeline matches the original target end to end; agent fleet is queryable from one place.

### Stage 7 — Parallel Execution + Executive Agent
**Goal:** Many epics running concurrently; one plain-language entry point.
**Builds:** Concurrency caps, BullMQ migration, Executive Agent, productivity dashboard, batched daily review workflow.
**Definition of done:** 10–20 features in flight concurrently with stable failure rates and one Executive Agent entry point a non-technical stakeholder can use.

## Feasibility Notes Carried Forward

Two permanent, deliberate limits apply at every stage: no agent ever deploys to production without human approval, and no fully autonomous 24/7 operation with zero human checkpoints will be built, regardless of how capable the agents become. These are safety decisions, not capability gaps — see `05`, ADR-010, and `17_Security_Handbook.md`.
