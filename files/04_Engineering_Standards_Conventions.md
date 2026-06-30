# 04 — Engineering Standards & Conventions

**Applies from:** Stage 0
**Related:** `02_System_Architecture_Blueprint.md`, `20_Testing_Strategy.md`

---

## Coding Standards

TypeScript everywhere, strict mode on (`"strict": true` in `tsconfig.json`), no implicit `any`. Every agent output schema (plans, subtasks, review findings) is defined as a Zod schema, not a loose object — agents producing structured output must validate against it before the result is accepted. Functions over classes where reasonable; React components are functional with hooks. Naming: `camelCase` for variables/functions, `PascalCase` for types/components, `kebab-case` for file names, `SCREAMING_SNAKE_CASE` for env vars.

## Folder / Monorepo Standards

```
apps/
  web/                  — Mission Control Dashboard (Next.js)
packages/
  task-engine/          — Task Queue, API routes
  agent-runtime/        — Claude Agent SDK wiring, agent role definitions
  repo-tools/           — Repository Intelligence Service client
  policy-engine/        — Policy rules and enforcement
  event-bus/            — Event publishing/subscribing
  shared-types/         — Zod schemas, shared TypeScript types
  shared-db/            — Database client, migrations
```

New packages are added under `packages/` as new components are introduced (see `02_System_Architecture_Blueprint.md`). Nothing goes directly in `apps/web` except UI — business logic lives in packages so it's testable in isolation and reusable.

## Git Standards

Branch naming: `stage-N/short-description` for roadmap work, `fix/short-description` for bugs. Commits follow Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`). Every agent-proposed change happens in an isolated git worktree (never directly on `main`) per `13_Policy_Engine_Specification.md`. Pull requests require: a linked task ID, a passing CI run (lint + typecheck + test), and human approval before merge — no exceptions, including for agent-authored PRs.

## Security Standards

Never commit `.env` files or secrets — enforced both by `.gitignore` and by the Policy Engine's PreToolUse hook, which blocks any agent write to `.env*` or `secrets/**` regardless of prompt instructions. Dependencies are reviewed before adding (no installing packages an agent suggests without a human checking it first). All credentials live in environment variables, injected at runtime, never passed in agent prompts. Full detail in `17_Security_Handbook.md`.

## Definition of Done — by Work Type

| Work Type | Definition of Done |
|---|---|
| Human-written feature | Passes CI, has tests, reviewed and approved by another engineer, merged |
| Agent-proposed plan (Stage 1) | References real files, is internally consistent, marked `ready_for_review` |
| Agent-proposed patch (Stage 2+) | Passes typecheck/lint/test in its worktree, reviewed by Code Review Agent, approved by a human, merged |
| New agent role (Stage 4+) | Has a role file extending the shared base template (`06_Agent_SDK_Specification.md`), scoped tool access, tested against at least 3 representative tasks before being added to the dispatch table |
| New Policy Engine rule | Documented in `13_Policy_Engine_Specification.md` with the trigger condition and required approval role, tested against at least one real scenario |

## Code Review Checklist (for human reviewers of agent-proposed changes)

Does the diff match what the plan said it would do? Are there any file changes outside the files the Architect Agent listed as impacted? Did QA actually pass, or was a check skipped? Does the Code Review Agent's findings list contain any unresolved "blocking" items? If yes to any concern, reject and let the agent retry rather than manually fixing it — manual fixes erase the audit trail and prevent the agent from learning the actual problem.
