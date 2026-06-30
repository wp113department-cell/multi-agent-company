# 14 — Scheduler Specification

**Applies from:** Stage 1 (basic queue), expanded Stage 5 (cost-aware), Stage 7 (concurrency)
**Related:** `02_System_Architecture_Blueprint.md`, `12_Event_Bus_Specification.md`

---

## Scope, Defined Precisely

This system does not run its own compute — every agent makes API calls to Claude. There is no GPU or CPU fleet to schedule workloads across. What's actually being scheduled is: how many tasks/epics are allowed to run concurrently, and in what priority order, given a job queue. This is a deliberately narrower (and correctly-sized) problem than a Kubernetes-style compute scheduler, and the implementation below is sized to match it — see `05`, ADR-009 for the broader reasoning on not over-building infrastructure for a problem the architecture doesn't have.

## Stage 1 — Basic Queue

A `priority` field on `dev_tasks` (`low`/`medium`/`high`); Inngest picks up `pending` tasks and triggers the agent runtime. No concurrency cap needed yet at single-agent, single-task-at-a-time scale.

## Stage 5 — Cost-Aware Gating

Before an epic begins execution, the Cost Controller (part of the Manager Agent) produces an estimate — expected token usage, approximate dollar cost, expected runtime — based on the Task Decomposer's subtask count and complexity, refined over time using historical averages from completed epics. Epics above a configurable cost threshold require explicit human approval before any agent starts working, not just at the end. This estimate vs. actual is shown on the Epic Approval dashboard view.

## Stage 7 — Concurrency

| Parameter | Stage 7 Initial Value | Notes |
|---|---|---|
| Max concurrent epics | 10–20 | Scaled up only after monitoring shows stable failure rates at the current cap |
| Per-epic worktree namespacing | Always on | Prevents concurrent epics from colliding on the same files |
| Retry/timeout | `max_turns` per agent run; 3 retries per subtask; epic halts if 2+ subtasks fail repeatedly | Same limits as Stage 2/4, applied per concurrent epic |
| Queue backend | Redis + BullMQ | Migrated from Inngest once throughput under concurrent load requires it |

## Agent Assignment

The scheduler assigns work to agents by querying the Agent Registry (`06_Agent_SDK_Specification.md`) for capability match (e.g., "needs Docker access for this subtask") rather than hard-coded agent-type references, so adding a new specialist agent later doesn't require touching scheduler logic — just registering the new agent with accurate capability tags.

## What's Not Being Built

A general-purpose, Kubernetes-style scheduler handling CPU/GPU allocation, bin-packing, or node affinity. This architecture has no compute nodes to allocate — only API call concurrency and human review throughput to manage, both of which the queue + concurrency cap + Cost Controller above handle at the actual scale this system operates at.
