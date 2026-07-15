# Tomorrow's Session Plan — Final Push to ~99%
Date: 2026-07-16
Starting state: v1.1.0, 990 tests passing, 0 failing

---

## What's Left (8 items + final docs)

### 1. Frontend Login Screen — P1
**Why:** JWT auth is fully built in backend (`/api/auth/login`, `/api/auth/me`, `/api/auth/setup`). Frontend has no login page — any user can access the UI.
**Work:**
- `apps/web/app/login/page.tsx` — login form, calls `POST /api/auth/login`, stores JWT
- `apps/web/middleware.ts` — redirect unauthenticated requests to `/login`
- Logout button in nav header
- `apps/web/lib/auth.ts` — helper to read/write token

### 2. Playwright E2E Tests — P1
**Why:** Doc 20 (Testing Strategy) requires E2E tests. Currently 0 browser tests.
**Work:**
- `e2e/` folder at repo root
- `playwright.config.ts` — target `http://localhost:3000`
- Tests: login → create task → view task list → approve task → logout
- Add `npx playwright test` step to `.github/workflows/ci.yml`

### 3. ~21 More Tools (reach 190-tool vision) — P1
**Why:** tools_agents.md vision is 190 tools. Currently 169 built. 21 remaining.
**Work:** Add to `backend/app/agents/tools.py` + wire handlers:
- `git_merge`, `git_reset`, `git_stash`, `git_tag` (4 git extras)
- `run_background`, `kill_process`, `list_processes` (3 process mgmt)
- `zip_files`, `unzip_files`, `copy_file`, `move_file` (4 file ops)
- `send_slack_message`, `create_linear_issue`, `create_github_issue` (3 MCP integrations)
- `generate_diagram`, `render_mermaid`, `export_pdf` (3 docs)
- `set_env_var`, `read_env_var`, `list_env_vars` (3 env helpers, read-only safe versions)
- Remaining 1: `check_url_status`
- Write tests in `backend/tests/test_new_tools.py`

### 4. ~19 More Agents (reach 60-agent vision) — P1
**Why:** tools_agents.md vision is 60 agents. Currently 41 wired in dispatch, 48 built. 19 more needed.
**Work:** Build + add to `_REGISTRY` in `specialized_agents.py`:
- `infra_agent` — cloud infra review (Terraform, K8s)
- `test_writer_agent` — generates pytest/jest test suites
- `code_explainer_agent` — plain-English explanation of code
- `data_pipeline_agent` — ETL/pipeline design
- `api_designer_agent` — REST/GraphQL API design
- `env_checker_agent` — validates environment config
- `cost_estimator_agent` — estimates cloud cost from code
- `incident_responder_agent` — triage and root cause
- `onboarding_agent` — generates onboarding docs for new devs
- `localization_agent` — i18n/l10n review
- `accessibility_agent` — WCAG audit
- `compliance_agent` — GDPR/SOC2 checklist
- `load_test_agent` — generates k6/locust load test scripts
- `pair_programmer_agent` — interactive step-by-step coding guide
- `spike_agent` — time-boxed research spike with findings report
- `rollback_agent` — generates rollback plan for a deploy
- `runbook_generator_agent` — writes ops runbook from code
- `slo_agent` — defines SLO/SLA targets from service description
- `feature_flag_agent` — feature flag review and cleanup
- Role files in `backend/roles/` for each
- Wire into `_REGISTRY`, add basic tests

### 5. Dark Mode Toggle — P2
**Why:** SELLABILITY_GAP.md P2. UI currently has no dark/light toggle.
**Work:**
- `apps/web/components/ThemeToggle.tsx` — sun/moon icon button
- Use Next.js `next-themes` package or CSS class toggle on `<html>`
- Persist preference to `localStorage`
- Add to nav header

### 6. Cost Dashboard in UI — P2
**Why:** SELLABILITY_GAP.md P2. Cost data exists in DB (`agent_runs.tokens_in/out`) — no UI surface.
**Work:**
- `apps/web/app/cost/page.tsx` — bar chart per agent/per day, total spend counter
- Calls existing `GET /api/metrics` endpoint (already built)
- Show: total tokens this week, cost estimate per agent, most expensive tasks

### 7. Memory Category Split — P2
**Why:** Doc 11 (Memory System) requires Architecture, Failure, Task, Learning as separate categories.
**Work:**
- Migration 010: add `category` enum column on `engineering_memory` table
- `backend/app/api/memory.py`: accept `?category=architecture|failure|task|learning` filter
- Update memory agent prompts to tag category on save

### 8. 90-Day Log Retention — P2
**Why:** Doc 11 specifies automated 90-day archival of task_logs.
**Work:**
- `backend/app/services/retention.py` — `enforce_retention_policy()` async fn
- Deletes `task_logs` rows older than 90 days
- Scheduled RQ job OR background task on `/health`

---

## Infra (cannot be done in code session)
- **Actual cloud deploy** — Vercel + Supabase + staging env. This is infra provisioning work (needs API keys, billing, DNS). `vercel.json` + `docker-compose.yml` are already written and ready. Do this separately after the code session.

---

## Final Step (always last)
- Update `PROJECT.md` with full session summary
- Run `pytest backend/tests/ -v` + `mypy backend/ --strict` — must be 0 failures
- Write `docs/reports/FINAL_SESSION_REPORT.md`
- Commit: `feat: final session — login, E2E, 21 tools, 19 agents, dark mode, cost dashboard, memory split, retention`
- Tag: `v1.2.0`

---

## Do NOT redo (already done)
- 48 agents built, 41 wired, 169 tools — base is solid, tomorrow adds on top
- Sentry, slowapi, JWT auth, S3 dispatch, alerting, chat persistence — done
- Migrations 001–009, Procfile, docker-compose, vercel.json, ci.yml — done
- Eval suite (evals/) — done
- 990 tests passing — baseline to build on

---

## Session order (priority first)
1. Tools (+21) — pure Python, fast, high spec-doc impact
2. Agents (+19) — Python, adds real dispatch capabilities
3. Frontend login screen — TypeScript/Next.js
4. Dark mode toggle — TypeScript, small
5. Cost dashboard — TypeScript, builds on existing /metrics API
6. Playwright E2E — builds on login screen being there
7. Memory category split + retention — migration + service
8. Final docs + commit + tag v1.2.0
