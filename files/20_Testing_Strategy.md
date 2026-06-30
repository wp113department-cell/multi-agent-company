# 20 — Testing Strategy

**Applies from:** Stage 1, expanded each stage
**Related:** `04_Engineering_Standards_Conventions.md`, `06_Agent_SDK_Specification.md`

---

## Unit Testing

Every package (`task-engine`, `agent-runtime`, `repo-tools`, `policy-engine`, `event-bus`) has its own unit tests (Vitest or Jest) for pure logic — Zod schema validation, Policy Engine rule matching, Context Builder assembly logic — run in CI on every PR. Target: meaningful coverage of business logic, not a coverage-percentage target pursued for its own sake.

## Integration Testing

The Task Queue API (`08_API_Specification.md`) is tested end-to-end against a real test database: create a task, verify status transitions, verify log entries are written correctly. Agent dispatch logic (Stage 4+) is tested by mocking the Claude API response and verifying the correct subagent is triggered with the correct scoped tools.

## Agent Evaluation Testing (the part standard software testing doesn't cover)

This is the most important and most often-skipped category for an agentic system: a fixed, version-controlled set of representative tasks (starting with 10–15 at Stage 1, growing over time) is run against each agent whenever its prompt, tools, or underlying model changes, and the output is compared against expected characteristics (does the plan reference real files? does the diff pass the same checks a human reviewer would apply?). This catches silent quality regressions — an agent that still "works" but produces noticeably worse plans after a prompt tweak — that unit tests can't catch, because the failure mode is a quality drop, not a crash. This test suite is maintained in `packages/agent-runtime/evals/` and run before any change to an agent role file is merged.

## End-to-End Testing

Stage 1: submit a task through the dashboard → verify a plan is generated and displayed correctly. Stage 2: submit a task → verify a reviewable diff appears and the approve/reject flow works. Stage 4: submit a task → verify it flows through PM → Architect → Decomposer → Dev → QA → Review without manual intervention, for a known-good representative task. Stage 5: submit a goal → verify a full epic completes and reaches the batched approval screen.

## Load / Concurrency Testing

Deferred until Stage 7, when concurrent epic execution is actually part of the architecture (`14_Scheduler_Specification.md`). Testing concurrency behavior before there's real concurrent infrastructure to test against would be testing against a simulation, not the real system — better spent once the Redis + BullMQ migration is in place.

## Security Testing

Policy Engine rules are tested directly: attempt (in a test environment, never against real infrastructure) to have a test agent write to `.env`, attempt a denylisted Bash command, and verify the PreToolUse hook blocks it every time, for every agent role. This is part of the standard test suite, not a separate periodic exercise — a regression here is a critical bug, caught the same way any other regression is.

## Regression & Acceptance Testing

Every stage's "Definition of Done" (`03_Technical_Execution_Roadmap.md`) is the acceptance criteria for that stage — before moving to the next stage's work, the prior stage's defined behavior is verified against the agent evaluation suite and end-to-end tests above, not just assumed to still work because it worked once.

## What's Deferred

Formal, dedicated performance/load testing infrastructure beyond what's described above is not built ahead of Stage 7. Penetration testing by a third party is worth commissioning once the system handles production-consequential work — premature and not cost-effective to commission for an internal tool still in early stages.
