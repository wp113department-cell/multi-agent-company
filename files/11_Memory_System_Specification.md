# 11 — Memory System Specification

**Applies from:** Stage 3 (short-term), Stage 6 (long-term)
**Related:** `10_Repository_Intelligence_Specification.md`, `02_System_Architecture_Blueprint.md`

---

## Two Kinds of Memory

This system deliberately keeps memory split into two clearly scoped layers rather than one generalized "knowledge graph," because they have different lifetimes, different consumers, and different failure modes.

## Short-Term Memory (Stage 3)

Scope: a single task or epic's execution. Implementation: LangGraph's built-in state and checkpointing, persisted to Postgres. Contains: current objective, current step, prior steps, retry count, accumulated context, tool outputs so far. Lifetime: as long as the task/epic is active; retained afterward as part of the task's audit trail (`task_logs`, `artifacts`) but not actively queried by future tasks unless promoted into long-term memory.

## Long-Term Memory — Engineering Memory (Stage 6)

Scope: across all completed tasks and epics, over time. Implementation: completed tasks' problem statements, plans, patches, outcomes, and any errors/fixes encountered are embedded and stored in pgvector (or Qdrant at scale). Consumers: the Architect Agent and Context Builder query this as an additional input alongside the Repository Intelligence Service's structural graph — so a new task similar to one solved before benefits from what was learned, including which approaches failed and why.

### Sub-categories within Engineering Memory

| Category | Captures |
|---|---|
| Task Memory | What was asked, what was delivered, how long it took |
| Architecture Memory | Technical decisions made by the Architect Agent and their outcomes |
| Failure Memory | What went wrong, what the error was, how it was fixed (or why it stayed blocked) |
| Learning Signal | Which prompts/tool combinations correlated with retries or failures — feeds future prompt and policy refinement, reviewed by engineers rather than auto-applied |

The "Learning Signal" category is intentionally framed as a reviewed input to human-driven prompt improvements, not an automated self-modifying loop — see `05`, ADR-010 reasoning extended to agent self-modification: no system component changes its own governing rules without a human reviewing the change.

## Retention Policy

`task_logs` and `agent_runs`: retained in full for 90 days (hot), then archived to cheaper storage rather than deleted, since audit history has long-term value. `artifacts` (plans, diffs, test results): retained indefinitely while linked to an active or recently completed task; archived alongside their task after 90 days. Engineering Memory embeddings: retained indefinitely — this is the system's accumulated experience and its value compounds over time, unlike raw logs.

## What's Not Being Built Yet

A separate, generalized "knowledge graph" system beyond the Repository Intelligence Service (structural) and Engineering Memory (experiential) — these two cover the actual near-term need. A unified graph database merging both is worth considering only once both have real usage data showing where the current split creates friction.
