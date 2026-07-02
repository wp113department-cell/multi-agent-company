# ADR 004 — Single Zod-validated config module, no inline env reads

**Status:** Accepted  
**Date:** 2026-07-02

## Context

Multiple packages were reading `process.env` directly with inline fallbacks (e.g. `process.env.AGENT_MODEL ?? "claude-sonnet-4-6"`). This violates the ZERO HARDCODING RULES and makes it hard to audit what configuration the system actually uses.

## Decision

All env var access goes through `packages/shared-config/src/index.ts` → `getConfig()`. No package reads `process.env` directly (except `shared-config` itself). Model names, retry limits, paths, and flags are all declared once in the Zod schema with documented defaults.

## Rationale

- **Single audit point**: to know every config value the system can receive, read one file
- **Type safety**: `getConfig()` returns a fully-typed `Config` object — no string coercion bugs
- **Fail-fast**: missing required vars (e.g. `DATABASE_URL`, `ANTHROPIC_API_KEY`) crash at startup with a clear message, not at first use 10 minutes into a task
- **Swap without code changes**: changing `MODEL_PLANNER` from Sonnet to Opus requires one env var change, zero code changes
- **`.env.example` always in sync**: the Zod schema and `.env.example` are the same list of vars — one is the machine-readable spec, the other is the human-readable guide

## Consequences

- Every package that reads config must depend on `@gridiron/shared-config`
- `_resetConfig()` is exported for test isolation (reset singleton between tests)
- The schema must be updated whenever a new env var is introduced — enforced by code review
