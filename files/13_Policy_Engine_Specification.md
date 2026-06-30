# 13 — Policy Engine Specification

**Applies from:** Stage 2 (v1), expanded Stage 5 (v2)
**Related:** `04_Engineering_Standards_Conventions.md`, `17_Security_Handbook.md`, `06_Agent_SDK_Specification.md`

---

## Principle

Safety and approval rules are executable config, not prose buried in a prompt. A prompt can be misread or ignored under unusual phrasing; a rule enforced in application code, before the action executes, cannot be talked around.

## Policy Engine v1 (Stage 2) — PreToolUse Hook

Implemented as a hard-coded denylist checked before every Write/Edit/Bash tool call:

```
DENY if path matches: .env, .env.*, **/secrets/**, .github/workflows/**
DENY if command matches: deploy, kubectl apply, terraform apply, rm -rf
```

Exit code 2 from the hook denies the call outright; the agent receives a clear denial message and must report it rather than retry differently. This is enforced in application code at the tool-call layer, not as an instruction the model could be prompted around.

## Policy Engine v2 (Stage 5) — Config-Driven Rules Table

```sql
policies (
  policy_id UUID PRIMARY KEY,
  trigger_pattern TEXT,        -- e.g. "files matching api/customer/**"
  required_approval_role TEXT, -- e.g. "architect", "security", "human"
  blocking BOOLEAN,            -- does execution halt until approved, or just flag?
  active BOOLEAN
);
```

The Manager Agent and Architect Agent both check this table before proceeding past certain points in the pipeline. Adding a new rule is an insert into this table, not a prompt-engineering exercise across every affected agent.

## Rule Categories

| Category | Example |
|---|---|
| Filesystem rules | Never write to `.env*`, `secrets/**` |
| Git rules | No force-push to `main`; all changes via worktree + PR |
| Deployment rules | No agent ever has deploy credentials; deploy is always a human action |
| Approval rules | Changes touching `api/customer/**` require Architect sign-off before coding starts |
| Database rules | Any migration file requires human approval before the QA stage runs, not just before merge |
| Security-sensitive rules | Changes touching `auth/**` require a Security review step (added once a Security Agent role exists) |
| Retry limits | Max 3 self-correction attempts per task before escalating to `blocked` |
| Risk levels | Tasks are tagged `low`/`medium`/`high` risk by the Architect Agent; `high` risk always requires human plan approval before any coding agent starts, even before Stage 5's batched epic approval |

## Escalation Path

A blocking policy violation halts the relevant agent and emits `task.blocked` (see `12_Event_Bus_Specification.md`), surfaced on the dashboard with the specific rule that triggered it. A non-blocking ("flag") policy logs the concern in `task_logs` and continues, surfaced for review at the next approval checkpoint rather than halting execution.

## Worked Examples

"DB migrations require human approval before QA" — `trigger_pattern: "**/migrations/**"`, `required_approval_role: "human"`, `blocking: true`. The migration file is generated and reviewed by a human before the QA Agent even attempts to run it against a test database.

"Customer-facing API changes require Architect sign-off" — `trigger_pattern: "api/customer/**"`, `required_approval_role: "architect"`, `blocking: true`. The Task Decomposer cannot dispatch a subtask touching this path to a Backend Agent until the Architect Agent has explicitly signed off on the approach.
