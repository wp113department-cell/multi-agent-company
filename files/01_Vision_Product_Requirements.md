# 01 — Vision & Product Requirements Document (PRD)

**Applies from:** Stage 0
**Related:** `03_Technical_Execution_Roadmap.md`, `15_Mission_Control_Dashboard_Specification.md`

---

## Company Vision

Gridiron AI is building an AI Workforce OS — a platform offering multiple AI-driven departments (receptionist, SDR, marketer, recruiter, accountant, operations, and more) to customers. The Developer Department, specified across this document suite, is the first internal department: an AI engineering team that helps Gridiron build and maintain those other departments faster than a conventional engineering team could.

This document covers the Developer Department only. It is the first proof point for the larger Workforce OS vision, not a description of that full vision — see `05_Architecture_Decision_Records.md` (ADR-009) for why the rest of the Workforce OS is deliberately not being designed yet.

## Problem Statement

Gridiron's product roadmap requires building and maintaining many AI agent products in parallel. A conventional human-only engineering team can't keep pace with that roadmap. The Developer Department exists to multiply engineering throughput: one or more AI agents that can read the existing codebase, plan a change, write it, test it, and present it for human approval — reducing the time from "feature requested" to "feature ready to ship."

## Goals

The system should let a person describe a development task in plain language and receive back a working, tested, reviewed code change ready for human approval — without that person needing to write the code themselves, while keeping every change auditable and reversible.

## Non-Goals (explicitly out of scope)

- Fully autonomous deployment with no human approval — never in scope, by design (see `05`, ADR-010)
- Building agents for non-Developer departments (Sales, Marketing, HR, etc.) — out of scope until the Developer Department has shipped and a second department is formally scoped
- Supporting AI models other than Claude in the near term — see `05`, ADR-008
- A generic, externally-sellable "Agent OS" product — this is internal tooling for Gridiron first

## Target Users

Primary: Gridiron's own engineering team and leadership, who submit development tasks and review agent output. Secondary (future): non-technical Gridiron stakeholders who, from Stage 7 onward, can describe a feature goal directly to the Executive Agent without going through an engineer.

## Scope by Phase

| Phase | Scope |
|---|---|
| Phase 1 (Stages 0–2) | Single agent: reads repo, plans, proposes reviewable code changes. No auto-merge. |
| Phase 2 (Stages 3–4) | Repository understanding, multi-step planning, specialist coding agents, automated testing. |
| Phase 3 (Stages 5–6) | Manager Agent orchestration, Research and Documentation agents, batched approvals. |
| Phase 4 (Stage 7+) | Parallel execution across many features at once, Executive Agent entry point. |

Full detail in `03_Technical_Execution_Roadmap.md`.

## Success Metrics

| Stage | Metric | Target |
|---|---|---|
| 1 | Plan accuracy: % of agent-generated plans a human approves without major rework | ≥ 70% on small/medium tasks |
| 2 | Diff acceptance rate: % of proposed patches approved with no or only minor edits | ≥ 60% |
| 3–4 | Time from task submission to reviewable diff (for a well-scoped feature) | Same-day for small features |
| 5 | Epic approval rate: % of epics approved on first review without escalation | ≥ 50%, improving over time |
| 6–7 | Concurrent epics in flight with stable failure rates | 10–20 sustained without manual intervention |

These targets are starting estimates, not contractual guarantees — they should be revisited after the first month of real Stage 1 usage against real tasks.

## Functional Requirements

The system must: accept a development task in plain language; produce a written implementation plan referencing real files in the repository; (from Stage 2) propose a code diff in an isolated environment; (from Stage 3) decompose complex tasks into subtasks handled by specialist agents; (from Stage 4) run automated tests and self-correct failures within a retry limit; (from Stage 5) batch related changes into a single human-reviewable approval; and at every stage, log every action taken for audit purposes.

## Non-Functional Requirements

**Safety:** no agent may write to `.env` files, secrets, or deployment configuration; no agent may deploy to production; every code change happens in an isolated git worktree until approved.

**Auditability:** every agent action (file read, file write, command run, decision made) is logged with timestamp, task ID, and agent identity, and is retrievable from the dashboard.

**Cost control:** from Stage 5, no epic begins execution without an upfront cost/time estimate, and epics above a configurable cost threshold require approval before starting, not just at the end.

**Reliability:** every agent run has a maximum retry limit; failed tasks are surfaced for human review rather than retried indefinitely.

## Long-Term Vision

If the Developer Department succeeds, Gridiron intends to apply the same pattern (task queue, planning subsystem, specialist agents, policy-gated approval) to other departments. That expansion is intentionally not designed in advance — see `05`, ADR-009, for the reasoning, and revisit this section once Stage 5 has shipped.
