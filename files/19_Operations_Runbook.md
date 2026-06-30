# 19 — Operations Runbook

**Applies from:** Stage 1
**Related:** `16_Observability_Specification.md`, `17_Security_Handbook.md`

---

## Checking System Health

Mission Control's Task List page shows the current state of every active task at a glance (status badges). Sentry shows any runtime exceptions in the last 24 hours. The Agent Registry view (Stage 6+) shows whether any agent type's success rate has dropped recently.

## Pausing or Killing a Runaway Task

From the Task Detail page, mark the task `blocked` — this halts any further agent action on it immediately (the agent runtime checks task status before each step and stops if it's no longer `pending`/`planning`/`coding`/`testing`). The agent's worktree is preserved, not deleted, so the state at the moment of intervention is inspectable. If a task is stuck in a way the dashboard action doesn't resolve, the underlying Inngest/BullMQ job can be cancelled directly from that platform's own dashboard.

## Rolling Back a Bad Merge

Standard `git revert` on the merge commit — no custom rollback tooling is needed or built, since every agent-authored change went through the standard PR + human approval flow (`04_Engineering_Standards_Conventions.md`) and lives in normal git history like any other commit.

## Handling a Blocked Task

Blocked tasks appear on the dashboard with the specific reason (Policy Engine rule triggered, retry limit exceeded, or QA failure the agent couldn't self-correct). Read the `task_logs` timeline for full context, then either: fix the underlying issue and re-trigger the agent from where it left off, or close the task and re-scope it if the original request was ambiguous or infeasible as written.

## Common Scenarios

| Scenario | Action |
|---|---|
| Agent stuck in a retry loop near its limit | Let it hit the limit and escalate naturally — don't manually intervene mid-loop, the retry cap is designed to surface this for review automatically |
| Agent proposes a change touching unexpected files | Reject the diff; check whether the Architect Agent's impacted-files list was wrong (Repository Intelligence issue) or the agent went outside its plan (agent behavior issue) |
| Policy Engine blocks something that should have been allowed | Don't bypass the block — review and adjust the relevant policy rule in `13_Policy_Engine_Specification.md`'s config, so the fix is permanent and auditable, not a one-off override |
| Dashboard shows a stalled heartbeat | Check Sentry for an unhandled exception in that run first; if none, the job may have died silently — cancel and re-trigger |

## Maintenance

Weekly: review the Agent Registry success-rate metrics (Stage 6+) for any agent type trending downward, which usually signals a prompt or tool issue worth investigating before it causes more failed tasks. Monthly: review `failed_events` (Event Bus dead-letter log, `12_Event_Bus_Specification.md`) for recurring patterns worth fixing at the integration level rather than continuing to retry around.

## Escalation

This system is operated by the team building it — escalation at this stage means flagging in the team's existing communication channel, not a formal on-call rotation. Revisit this section once the system handles work consequential enough to need defined on-call coverage.
