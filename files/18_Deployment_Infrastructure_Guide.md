# 18 — Deployment & Infrastructure Guide

**Applies from:** Stage 1, expanded Stage 7
**Related:** `02_System_Architecture_Blueprint.md`, `09_Database_Design_Specification.md`

---

## Stage 1–6 Infrastructure

| Component | Where it runs |
|---|---|
| Next.js dashboard + API routes | A standard Node hosting platform (e.g., Vercel) — handles build/deploy, preview environments per PR, and scaling without custom infrastructure work |
| PostgreSQL (+ pgvector) | Supabase-hosted Postgres |
| Background jobs | Inngest (managed) |
| Object/artifact storage | Supabase Storage or equivalent S3-compatible bucket |
| Error tracking | Sentry (managed) |

This setup deliberately avoids container orchestration, custom CI/CD beyond standard checks, and self-managed infrastructure at this stage — there's no operational benefit to it yet, and it would cost a 2–6 person team real time better spent on the product itself.

## Environments

Three environments: `development` (local, each engineer's machine, can point at a shared dev database or local Postgres), `staging` (mirrors production, used for testing agent behavior against realistic data before it affects real tasks), `production` (the real Mission Control instance the team uses daily). Agent worktree operations never touch `production` infrastructure directly — they operate on git worktrees of the actual codebase repository, which is a separate concern from which environment the dashboard/API are deployed to.

## CI/CD

GitHub Actions on every pull request: lint, typecheck, unit tests, integration tests for the Task Queue API. No deploy happens automatically on agent-authored PRs — merge to `main` still requires human approval (`05`, ADR-010), and deploy to `production` is a separate, manually-triggered step even after merge, at every stage currently scoped.

## Stage 7 — Scaling Infrastructure

| Component | Change |
|---|---|
| Background jobs | Migrate from Inngest to self-managed Redis + BullMQ if Inngest's throughput limits are hit under concurrent epic load |
| Vector search | Migrate from pgvector to Qdrant if embedding volume/query load justifies a dedicated vector store |
| Event Bus | Migrate from Postgres `LISTEN/NOTIFY` to Redis Streams if event volume requires it |

Each migration above is conditional on an actual, measured limit being hit — not scheduled to happen regardless of whether it's needed, consistent with the architecture's general approach to infrastructure (`05`, ADR-005 through ADR-007).

## What's Deferred

Kubernetes, multi-region deployment, and formal disaster-recovery infrastructure (cross-region replication, defined RPO/RTO targets) are not part of the architecture at any stage currently scoped. This system's actual infrastructure footprint — one web app, one database, a managed job queue — does not yet justify that operational complexity. If Gridiron's broader infrastructure strategy later requires this system to meet specific availability or compliance targets, that becomes a dedicated, separately-scoped workstream once those targets are actually defined, not a speculative build now.
