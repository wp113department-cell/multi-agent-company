# 17 — Security Handbook

**Applies from:** Stage 1, expanded each stage
**Related:** `13_Policy_Engine_Specification.md`, `04_Engineering_Standards_Conventions.md`

---

## Secrets Handling

No secret (API key, database credential, signing key) is ever placed in code, in an agent prompt, or in agent-readable context. All credentials live in environment variables injected at the runtime/deploy layer. The Policy Engine's PreToolUse hook (`13_Policy_Engine_Specification.md`) blocks any agent write to `.env*` or `secrets/**` at the application layer, regardless of what an agent is instructed or attempts to do.

## Authentication

Supabase Auth for all human users of the Mission Control Dashboard. Stage 1–4: single internal team, all authenticated users have full access — appropriate for a small team building the system itself. Stage 5+: roles are introduced (see Authorization below) as approval actions become consequential enough to restrict.

## Authorization (RBAC)

Right-sized to actual need at each stage rather than built in full upfront: Stage 1–4 has no granular roles. Stage 5 introduces an `approver` role (can approve/reject epics) distinct from a general `viewer` role (can see everything, approve nothing) — enforced at the API layer on the approval endpoints (`08_API_Specification.md`). Further role granularity (e.g., per-project approval scoping) is added only if and when the team genuinely needs it, not speculatively now.

## Sandbox / Isolation

Every coding agent operates inside an isolated git worktree (`05`, ADR-004), never directly against the checked-out repository. `Bash` tool access is scoped per role to specific allowed commands (typecheck/lint/test), never arbitrary shell execution. No agent, at any stage, holds deployment credentials — deploy is permanently a human action (`05`, ADR-010).

## Audit Logs

`task_logs` is the system's audit trail: every tool call, file read/write, and agent decision, timestamped and attributed to a specific agent run and task. This is retrievable and replayable from the dashboard for any task, at any time within the retention window (`11_Memory_System_Specification.md`).

## Incident Response (Right-Sized for Current Stage)

If an agent does something unexpected: the task can be manually marked `blocked` via the dashboard, which halts further agent action on it immediately; the worktree is preserved (not torn down) for inspection; the full `task_logs` timeline shows exactly what was attempted. A formal incident response playbook with defined severity levels and external communication procedures is appropriate once this system is handling production-consequential work at scale — premature to formalize before Stage 5+ usage establishes what kinds of incidents actually occur in practice. Until then, the response is: block the task, inspect the logs, fix or discard the worktree, and add a Policy Engine rule if the same class of issue could recur.

## Compliance

No compliance certification (SOC 2, HIPAA, etc.) is claimed or in scope for this internal tool at its current stage. If Gridiron's broader business later requires a compliance posture that extends to this system, that becomes a dedicated, separately-scoped workstream — this document does not assert compliance the system hasn't been audited for, and engineers should not represent it as compliant to anyone outside the team without that formal process having actually happened.
