# 06 — Agent SDK Specification

**Applies from:** Stage 1 (lifecycle), expanded at Stage 4 (specialist roles), Stage 6 (Agent Registry)
**Related:** `07_Tool_MCP_Specification.md`, `13_Policy_Engine_Specification.md`

---

## Purpose

Every agent in the system — Planner, Architect, Backend, Frontend, QA, Reviewer, DevOps, Research, Documentation, Manager, Executive — implements the same lifecycle and contract. This means adding a new agent role is "write a role file and register it," not "build a new system."

## Agent Lifecycle

```
created → planning → coding → testing → blocked | completed | failed
```

Every agent run starts when it's dispatched a task or subtask, and ends in exactly one of `completed`, `failed`, or `blocked` (awaiting human input). No agent run is left in an ambiguous state — this is enforced by the Task Engine, not left to agent discretion.

## Shared Base Template

Every agent role file (`.claude/agents/<role>.md`) extends a shared base template containing: standard safety rules (never touch `.env*`/`secrets/**`, regardless of task), standard logging behavior (every tool call and decision logged to `task_logs`), standard error handling (on unrecoverable error, mark `failed` with full context rather than retrying silently), and a standard heartbeat (agent reports `agent_runs.status` on a fixed interval so the dashboard can detect a stalled run).

Role-specific files then add: their system prompt, their scoped `tools:` list, their `isolation` mode, and their `max_turns` cap.

## Interface Every Agent Implements

| Stage | Responsibility |
|---|---|
| Planning | Given a task and Context Builder output, produce a structured plan (Zod-validated schema specific to the role — PM Agent outputs goals/constraints/acceptance criteria, Architect outputs impacted files/risks, etc.) |
| Execution | Carry out the plan using only its scoped tools; all file writes happen in an isolated worktree |
| Validation | Self-check output against its own output schema before marking complete; coding agents additionally wait for QA Agent confirmation |
| Cleanup | On completion or failure, the worktree is torn down (or preserved for `blocked` tasks pending human review) |
| Heartbeat | Periodic status write to `agent_runs`, visible on the dashboard |

## Context Contract

Every agent receives its task context exclusively through the Context Builder (`10_Repository_Intelligence_Specification.md`) — agents do not independently decide what files to read from scratch; they receive a pre-assembled, relevant context package, then may read further within their scoped tools if needed.

## Permissions Model

Tool access is scoped per role, principle of least privilege: read-only roles (Code Review Agent, Research Agent) have no `Edit`/`Write`/`Bash` tools at all — not instructed to avoid them, structurally unable to use them. Coding roles get `Edit`/`Write` scoped to worktree isolation. No role except a human action ever gets deploy credentials. Full tool matrix in `07_Tool_MCP_Specification.md`.

## Error & Event Contract

Every agent emits events to the Event Bus (`12_Event_Bus_Specification.md`) at defined transition points (`task.planned`, `subtask.assigned`, `qa.passed`, etc.) and writes structured log entries to `task_logs` for every meaningful action. On failure, the full error context (what was attempted, what tool failed, what the error message was) is preserved — never silently swallowed.

## State Contract

Shared LangGraph state (per task/epic) is the single source of truth for "what has happened so far." Agents read prior state to avoid redundant work and write their output back into state for the next agent in the pipeline to consume. State is checkpointed to Postgres after every node, so a crash resumes rather than restarts.

## Agent Registry (introduced Stage 6)

Once there are 8+ agent types, each is tracked in the Agent Registry: name, type, version, **capabilities** (tagged — `git`, `docker`, `sql`, `browser`, etc.), tool access, prompt reference, owner, and live success-rate metrics. The Manager Agent dispatches by capability tag rather than hard-coded agent names, so adding a new specialist later means registering it with the right capabilities, not modifying dispatch logic.

```sql
agents (
  agent_id UUID PRIMARY KEY,
  name TEXT,
  type TEXT,
  version TEXT,
  capabilities TEXT[],
  tools TEXT[],
  prompt_ref TEXT,
  owner TEXT,
  success_rate NUMERIC,
  avg_retries NUMERIC,
  last_updated TIMESTAMPTZ
)
```

## Adding a New Agent Role — Checklist

1. Define its output schema (Zod) and add it to `shared-types`
2. Write its role file extending the shared base template, with the minimum tool list it actually needs
3. Register it in the Agent Registry with accurate capability tags
4. Test it against at least 3 representative tasks before adding it to the dispatch table
5. Document any new Policy Engine rules its actions should trigger (e.g., a Security Agent's findings might require a blocking approval rule)
