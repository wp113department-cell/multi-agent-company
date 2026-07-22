# Deployment Guide — Gridiron Developer Department

Day 19 of the Fleet Enhancement Plan (`docs/FLEET_ENHANCEMENT_PLAN.md`) is
cloud deployment. **This document is prep only — no accounts were created
and nothing was deployed.** Everything below is verified to exist and work
locally; the remaining steps require your own Supabase/Railway/Render/Vercel
accounts and are manual by design (CLAUDE.md: "Deploy is a human action
forever").

Two independent runtimes deploy separately:
- `backend/` — Python FastAPI + LangGraph → Railway or Render (Vercel does
  not run long-lived Python servers)
- `apps/web/` — Next.js → Vercel

## 1. Database — Supabase Postgres + pgvector

1. Create a Supabase project. Copy the connection string.
2. Enable pgvector (SQL editor, once):
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Set `DATABASE_URL` to the Supabase connection string, using the
   **asyncpg** driver prefix:
   ```
   postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>
   ```
   Caution: Supabase's pooled connection ("Transaction" pooler / pgbouncer,
   usually port 6543) does not support the prepared statements asyncpg uses
   by default. Use the direct connection (port 5432) or Supabase's "Session"
   pooler mode — verify with a real `alembic upgrade head` run before
   trusting either.
4. Run all 17 migrations against Supabase:
   ```bash
   cd backend
   DATABASE_URL=postgresql+asyncpg://... alembic upgrade head
   ```
   (`migrations/env.py` reads `DATABASE_URL` directly — no separate config
   file to edit.) Migrations 001–017 cover every phase through Day 17
   (Credential Vault); nothing from Day 18 (streaming) added new tables.

## 2. Backend — Railway or Render

A `Procfile` already exists at the repo root:
```
web: cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: cd backend && rq worker gridiron-high gridiron-default --url ${REDIS_URL:-redis://localhost:6379/0} --with-scheduler
```
- The `web` process is required. The `worker` process is only needed if you
  set `QUEUE_BACKEND=rq` (default is `asyncio`, in-process — no worker
  needed for a first deploy).
- Point the platform at `backend/requirements.txt` for dependency install.
- Set every variable your deployment needs from `backend/.env.example`
  (93 documented variables — all optional except `DATABASE_URL` and
  `ANTHROPIC_API_KEY`, which crash startup with a clear message if unset).
  At minimum for a working deploy:
  - `DATABASE_URL` (from step 1)
  - `ANTHROPIC_API_KEY`
  - `JWT_SECRET_KEY` (generate: `openssl rand -hex 32`) if `JWT_AUTH_ENABLED=true`
  - `DEFAULT_ADMIN_PASSWORD` — change from the `gridiron123` default
  - `CREDENTIAL_ENCRYPTION_KEY` (generate via the command documented in
    `backend/.env.example`) — without it, vault-stored credentials
    (GitHub token, custom secrets) are stored in plaintext
  - `CORS_ORIGINS` — your Vercel frontend's real URL
- No secrets belong in any committed file — set them in the platform's
  dashboard (Railway/Render "Variables" tab), never in `vercel.json`,
  `Procfile`, or a committed `.env`.

## 3. Frontend — Vercel

`vercel.json` at the repo root builds the `apps/web` workspace with pnpm
(matches the CI workflow and the repo's `packageManager: pnpm@11.9.0`):
```json
{
  "buildCommand": "pnpm --filter @gridiron/web run build",
  "installCommand": "pnpm install --frozen-lockfile",
  "outputDirectory": "apps/web/.next"
}
```
Before this session, `installCommand`/`buildCommand` used `npm ci`/`npm run
build` from inside `apps/web` — `apps/web` has no `package-lock.json` of its
own (only a root `pnpm-lock.yaml`, since this is a pnpm workspace), so that
would have failed on a real Vercel build. Fixed to use pnpm directly.

Steps:
1. Import the repo into Vercel, framework preset "Next.js" (already set in
   `vercel.json`).
2. Set the `NEXT_PUBLIC_API_URL` environment variable in the Vercel
   dashboard to your deployed backend's public URL (step 2). `vercel.json`
   references it as a secret (`@gridiron_api_url`) — either create that
   secret via `vercel env add`, or replace the `env` block with a plain
   Vercel project environment variable of the same name.
3. `vercel.json`'s `rewrites` destination (`https://api.gridiron.example.com`)
   is a placeholder — update it to your real backend URL, or remove the
   `rewrites` block entirely and rely on `next.config.mjs`'s own
   `NEXT_PUBLIC_API_URL`-driven proxy (`apps/web/next.config.mjs`), which is
   already env-driven and requires no edit.

## 4. CI gate

`.github/workflows/ci.yml` already runs on every push/PR with no changes
needed:
- `backend` job: Postgres+pgvector service container, Alembic migrations,
  ruff, black --check, `mypy app/ --strict`, `pytest tests/ -v`
- `frontend` job: pnpm install, typecheck, eslint, `next build`
- `security` job: `pip-audit`

There is deliberately no deploy job — wire your platform's own
"deploy on push to main" integration (Railway/Render/Vercel all support
this natively) so deploys only happen after CI is green, per the plan's
"Deploy only on green main" requirement.

## 5. Health check

`GET /health` (`backend/app/main.py`) returns:
```json
{"status": "ok", "checks": {"db": "ok"}, "db": "ok", "agents": 72}
```
`agents` comes from `ensure_all_agents_registered()`, called at startup —
if this is below 72, something failed to import; check the deploy logs for
`"Fleet agent registry bootstrap failed"`.

## 6. Production smoke test (manual — do this yourself after deploying)

Once both services are live:
```bash
curl https://<your-backend>/health
```
Confirm `status: ok`, `agents: 72`. Then run one real task end-to-end
through the deployed frontend to confirm the full pipeline (PM → Architect
→ Decomposer → Coder) works against the live database and a real
`ANTHROPIC_API_KEY`. This is the plan's final success criterion and can only
be done after real infrastructure exists — it is not part of this session's
prep work.

## What was verified this session (no deployment performed)

- `backend/.env.example` documents all 93 real `Settings` fields (was
  missing 18; fixed).
- Root `.env.example` was stale TypeScript-era boilerplate (referenced a
  Zod schema that no longer exists) — replaced with a pointer to the two
  real env files (`backend/.env.example`, `apps/web/.env.example`, the
  latter newly added).
- `apps/web/next.config.mjs`'s backend URL is already env-var-driven
  (`NEXT_PUBLIC_API_URL`, falls back to `http://localhost:8000` for local
  dev) — no hardcoded production URL to fix.
- `vercel.json`'s install/build commands fixed from `npm ci` (would fail —
  no lockfile in `apps/web/`) to `pnpm` (matches the workspace and CI).
- `.github/workflows/ci.yml` already gates on pytest + mypy --strict for
  every push — no changes needed.
- `Procfile` already defines both `web` and `worker` processes correctly.
