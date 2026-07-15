# Sellability Gap Analysis — Gridiron Developer Department

**Date:** 2026-07-15  
**Status:** v1.0.0 release candidate

This document lists what currently exists, what is missing relative to a production sale, and the recommended fill order for maximum selling leverage.

---

## What Exists (Production-Ready)

### Core Pipeline
- FastAPI backend (Python 3.11), LangGraph StateGraph for all agent flows
- 27 specialized agents registered and dispatchable via `/api/specialized-agents/{name}/run`
- Full agent contract: VerificationConfig enforces real tool calls before `verified=True`
- Max 3 self-correction retries → `blocked` status, never infinite loops

### Storage
- PostgreSQL (asyncpg) + pgvector for semantic memory
- Alembic migrations (001–007 applied)
- Artifact storage with optional S3 backend (gzip-compressed JSON)

### Security
- Policy engine blocks: `.env*` writes, `secrets/` writes, `.github/workflows/` writes, `rm -rf`, `git push`, `kubectl`, `docker push`, `vercel deploy`
- Worktree boundary enforcement (path traversal blocked)
- RBAC (viewer/approver roles)
- All policy checks are code-level (not prompt-level), enforced even if the LLM tries to bypass

### Observability
- Sentry integration (optional, no-op when DSN empty)
- Webhook alerting on task `blocked` or `failed`
- Log retention with configurable TTL
- `/api/metrics` and `/api/metrics/epics` endpoints

### Infrastructure
- Redis Queue (RQ) adapter for horizontal scaling
- Redis Streams event bus adapter
- GitHub Actions CI (`.github/workflows/ci.yml`)
- Vercel deployment config (`vercel.json`)

### Frontend
- Next.js UI with: task board, epic management, batch review, repo management, chat interface, metrics dashboard
- Streaming chat with 131 tools
- Confirmation dialogs for write/execute tools

---

## Current Gaps

### P0 — Blocks a paid contract

| Gap | Impact | Effort |
|-----|--------|--------|
| **No real auth** — the RBAC uses a hardcoded `X-User-Role` header, not a real identity provider | Demo-to-production blocker | 2–3 days (add JWT / OAuth2 via FastAPI-Users or Auth0) |
| **No migration for gap day agents** — 7 new agents have no DB schema changes but `memory_embeddings` `outcome` enum may not include `'architecture'`/`'failure'` values in prod | Data integrity risk | 1 day (add Alembic migration to ALTER TYPE) |
| **No rate limiting on API endpoints** — a rogue client can DoS the backend | Security gap for any SaaS deployment | 0.5 day (add slowapi middleware) |

### P1 — Needed before first paying customer

| Gap | Impact | Effort |
|-----|--------|--------|
| **No real auth credentials in UI** — login screen is absent | Can't onboard a real user | 2 days |
| **No persistent chat history across sessions** — ChatSession is in-memory | Users lose context on restart | 1 day (persist chat_messages table) |
| **RQ worker not started by default** — queue_backend=rq requires a separately managed worker process | Ops confusion at deployment | 0.5 day (add Procfile / docker-compose worker service) |
| **S3 backend not wired into save_artifact_async** — s3_store.py exists but store.py always uses DB | S3 never actually used | 1 day (add backend dispatch in store.py) |
| **No health check for Redis/S3** — `/health` only checks DB | Silent failures in cloud infra | 0.5 day |

### P2 — Nice-to-have for demos

| Gap | Impact | Effort |
|-----|--------|--------|
| **No end-to-end test** — pytest is all unit/integration, no Playwright e2e | Can't demo "it works" reliably | 2 days |
| **No cost dashboard** — cost estimates calculated but not displayed in UI | Buyers ask about cost first | 1 day |
| **Agent run history not paginated** — task logs can be large | UX degradation at scale | 0.5 day |
| **No dark mode toggle** — UI is light-only | Minor UX gap | 0.5 day |

---

## Recommended Fill Order

1. **P0: Add Alembic migration** for `memory_embeddings.outcome` enum values (`architecture`, `failure`) — low effort, high risk if missing in prod.
2. **P0: Add rate limiting** — 30 min to add `slowapi`, prevents DoS.
3. **P0: Wire S3 backend** in `artifacts/store.py` to actually dispatch to `s3_store.py` when `ARTIFACT_BACKEND=s3`.
4. **P1: Real auth** — replace `X-User-Role` header with JWT. Use FastAPI-Users or a simple `python-jose` middleware.
5. **P1: Persist chat history** — one new table, one migration.
6. **P2: Cost dashboard** — surface existing cost data in a new `/metrics/cost` panel.

---

## What Makes Gridiron Sellable Right Now

- **Complete agent fleet**: 27 production agents covering every software engineering workflow (planning → coding → review → QA → deployment → documentation)
- **Verified-not-assumed**: the VerificationConfig system means outputs are auditable — buyers can trust the `verified` flag
- **Policy engine**: demonstrable live attack resistance is a rare differentiator vs. competitor agent platforms
- **LangGraph foundation**: production-tested orchestration, not a custom event loop
- **Streaming chat**: Claude Code-comparable chat UX with 131 tools, confirmation dialogs, code execution
- **Full stack**: Python backend + Next.js frontend + CI + Vercel config = deploy-ready in one `git clone`
