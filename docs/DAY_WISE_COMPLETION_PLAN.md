# Gridiron Developer Department — Day-Wise Gap Completion Plan
**Created:** 2026-07-15  
**Based on:** MASTER_PROMPT_PACK.md + tools_agents.md + main_client_share_file.md vs actual PROJECT.md state  
**Current tests:** 586 passed, 54 skipped, 0 failed

---

## AUTHENTIC STATUS SNAPSHOT

### Against MASTER_PROMPT_PACK (8 Days)

| Day | What It Covers | Status | % |
|-----|----------------|--------|---|
| Day 1 | Foundation, Task Queue, Planning Agent, Policy Engine, Worktrees, Diff UI | ✅ COMPLETE | 100% |
| Day 2 | Safe Code Proposal, Coder Agent, Self-Fix Loop, Approve/Reject | ✅ COMPLETE | 100% |
| Day 3 | Repo Intelligence (AST, pgvector, MCP), PM→Architect→Decomposer, Checkpoint, Human Interrupt | ✅ COMPLETE | 100% |
| Day 4 | Specialist Agents, QA Loop, Event Bus, Artifact Store, Tool Scoping | ✅ COMPLETE | 95% |
| Day 5 | Manager Agent, Epics, Cost Controller, Policy Engine v2, RBAC, DevOps Agent | ✅ COMPLETE | 100% |
| Day 6 | Research Agent, Docs Agent, Agent Registry, Engineering Memory (pgvector) | ✅ COMPLETE | 100% |
| Day 7 | Executive Agent, Goals API, Concurrency (semaphores), Queue Adapter, Metrics Dashboard | ⚠️ PARTIAL | 80% |
| Day 8 | Full Live Audit, FINAL_AUDIT_REPORT.md, SELLABILITY_GAP.md, v1.0.0 tag | 🔴 NOT DONE | 5% |

**MASTER_PROMPT_PACK Total: ~85%**

### Against tools_agents.md (Full Vision)

| Layer | Items in Spec | Items Built | % |
|-------|---------------|-------------|---|
| Layer 1: Tools | ~190 tool capabilities | ~100 built | ~52% |
| Layer 2: Agents | ~60 named agents | 36 built | ~60% |
| Layer 3: Infrastructure | 22 services | 18 built | ~82% |

**tools_agents.md Total: ~58%**

### Against Client Milestones (main_client_share_file.md)

| Milestone | Status |
|-----------|--------|
| 1 — Single agent (plan + repo) | ✅ 100% |
| 2 — Applies changes + runs tests | ✅ 100% |
| 3 — Fixes own errors | ✅ 100% |
| 4 — Multiple specialized agents | ✅ 100% |
| 5 — Full AI engineering department | ~88% (needs audit + missing agents) |

---

## SPECIFIC GAPS — WHAT IS MISSING

### MASTER_PROMPT_PACK Day 7 Gaps
- `BullMQQueueAdapter` raises `NotImplementedError` (stub only) — Python equivalent (Redis Queue / RQ) not implemented
- Redis Streams Event Bus adapter not built (Postgres-only; no `EVENT_BUS_BACKEND=redis` path)
- Live concurrency test with 3+ concurrent epics never formally run and documented

### MASTER_PROMPT_PACK Day 8 Gaps (100% missing)
- `docs/reports/FINAL_AUDIT_REPORT.md` — not written
- `docs/SELLABILITY_GAP.md` — not written
- `docs/ADD_A_NEW_AGENT.md` — not written
- `README.md` at production runbook quality — not done
- `v1.0.0` git tag — not created
- Formal hardcoding hunt (grep entire codebase for magic strings, verify .env.example)
- Formal hallucination hunt (every SDK call site vs installed package types)
- Formal infinite loop audit (every retry cap documented with file:line)
- Live attack tests: write .env, escape worktree, rm -rf, git push — all formally verified denied

### Wire-Up Gaps (built but not wired)
- Day 3 agents (9: performance_reviewer, style_reviewer, sprint_planner, business_analyst, migration_agent, schema_agent, ai_engineer, cleanup_agent, tech_debt_agent) NOT wired into `backend/app/api/agents.py` dispatch routing
- No `test_day3_agents.py` integration tests

### Tool Gaps (tools_agents.md Layer 1)
- **Browser/Playwright** (10 tools): `browser_driver.py` exists in repo_tools but NOT wired into `CHAT_TOOLS` or `chat_agent.py`. Missing: open_browser, navigate, click, type, screenshot, read_dom, extract_html, playwright
- **File types**: read_image, read_pdf, read_binary
- **Process management**: run_background (Popen), kill_process
- **Git**: git_merge, git_reset, generate_commit_message, create_pr (via gh CLI)
- **Smart search**: find_queue, find_worker
- **Editing**: insert_before, insert_after, delete_block, apply_patch, multi_file_edit
- **Testing**: run_single_test, run_folder_tests, build, benchmark
- **Documentation**: generate_changelog, generate_release_notes, summarize_folder, summarize_repo, architecture_diagram, mermaid_generator
- **MCP integrations**: GitHub (create_pr, list_prs, create_issue), Linear (create_issue), Slack (send_message), Jira — none wired
- **Security**: XSS scan, prompt_injection_scan, unsafe_eval_detect
- **Docker**: docker_compose in CHAT_TOOLS (handler in docker_agent but not chat agent)
- **DB**: backup_database, restore_database
- **Infra**: kubectl, helm

### Agent Gaps (tools_agents.md Layer 2 — missing agents)
- **Documentation Layer**: release_notes_agent, migration_docs_agent (migration_agent does DB schema, not docs)
- **Research Layer**: stackoverflow_agent, github_research_agent, best_practice_agent
- **Quality Layer**: unit_test_agent, integration_test_agent, load_tester, security_tester, regression_tester
- **Product Layer**: requirement_analyzer, user_story_generator
- **Architecture Layer**: system_design_agent, api_architect, database_architect, security_architect
- **DevOps Layer**: infrastructure_agent, cloud_agent, kubernetes_agent
- **Data Layer**: analytics_agent
- **AI Layer**: prompt_engineer_agent, rag_engineer_agent, embedding_engineer_agent, evaluation_agent, model_optimization_agent

### Infrastructure Gaps (tools_agents.md Layer 3)
- LSP Engine (Language Server Protocol for go-to-definition, type resolution)
- Sentry/external telemetry (task_logs ✅, but no error-tracking service)
- Scheduler (only weekly reindex; no cron job scheduler for agent tasks)
- Secrets Manager (vault; currently policy engine enforces no secret writes)

---

## DAY-WISE COMPLETION PLAN

### Gap Day 4 — Wire-Up + Test + Audit Prep
**Goal:** Close the "built but not wired" gaps and run the formal Day 8 Part A audit

**Tasks:**
1. Wire all 9 Day 3 agents into `backend/app/api/agents.py` (POST /api/agents/{name}/run dispatch)
2. Write `backend/tests/test_day3_agents.py` — unit tests for all 9 agents (handler factories, submit tools, verification configs)
3. **Hardcoding hunt** — grep entire codebase: `grep -r "claude-\|sk-ant-\|localhost:8000\|localhost:5432\|gridiron_dev_only\|port=\|3000\|0.0.0.0"` — every hit = move to config or justify
4. **Hallucination hunt** — for every external library call (anthropic, langgraph, sqlalchemy, alembic, voyageai), open installed package source and verify each call site
5. **Infinite loop audit** — list every retry/loop with its cap, file:line: `grep -rn "MAX_RETRIES\|max_retries\|MAX_ITER\|range(" backend/app/`
6. Run full test suite + write `docs/reports/GAP_DAY4_REPORT.md`
7. Update PROJECT.md

**Expected:** 600+ tests passing, 9 Day 3 agents fully wired, audit doc started

---

### Gap Day 5 — Browser Tools + MCP Integrations
**Goal:** Add Playwright browser tools and real MCP integrations to CHAT_TOOLS

**Tasks:**
1. **Browser tools** — wire `browser_driver.py` into CHAT_TOOLS + `chat_agent.py`:
   - `open_browser(url)` — launch headless Chromium via playwright
   - `navigate(url)` — navigate to URL
   - `click(selector)` — click DOM element
   - `type_text(selector, text)` — type into input
   - `screenshot()` — capture PNG, return base64
   - `read_dom()` — return page HTML
   - `extract_html(selector)` — extract specific element
2. Verify `playwright` installed, add to `requirements.txt`
3. **GitHub MCP** — test `npx @modelcontextprotocol/server-github` locally; if working: add github_create_pr, github_list_prs, github_create_issue tools
4. **Slack MCP** — verify `@modelcontextprotocol/server-slack` exists; add slack_send_message tool (with confirm dialog)
5. Write `backend/tests/test_day5_tools.py` — 50+ tests for browser + MCP tools
6. Update PROJECT.md

**Expected:** 650+ tests, CHAT_TOOLS count rises, browser agent capable

---

### Gap Day 6 — Missing Tool Categories
**Goal:** Fill remaining tool gaps from tools_agents.md Layer 1

**Tasks:**
1. **File type tools**: read_image (base64→text), read_pdf (pdfplumber), read_binary (hex dump)
2. **Process management**: run_background(cmd) → PID, kill_process(pid), stream_output(pid) → last N lines
3. **Git extras**: git_merge(branch), git_reset(mode, ref), generate_commit_message() → calls LLM with git diff, create_pr() → `gh pr create`
4. **Search extras**: find_queue() → grep for Queue/asyncio.Queue/BullMQ patterns, find_worker() → grep for Worker/consumer patterns
5. **Editing extras**: insert_before(file, anchor, content), insert_after(file, anchor, content), delete_block(file, start, end), apply_patch(file, patch)
6. **Testing extras**: run_single_test(test_id), run_folder_tests(folder), build(command)
7. **Docs extras**: generate_changelog(from_tag, to_tag) → parses git log, summarize_repo() → tree + key files
8. **Docker in chat**: add docker_compose(action, service) to CHAT_TOOLS
9. Write `backend/tests/test_day6_tools.py`
10. Update PROJECT.md

**Expected:** 720+ tests, CHAT_TOOLS ~130 tools

---

### Gap Day 7 — Missing Agents Round 2
**Goal:** Build the missing specialized agents from tools_agents.md Layer 2

**Priority agents (highest value):**
1. `release_notes_agent.py` — reads git log between tags → writes RELEASE_NOTES.md in versioned format
2. `evaluation_agent.py` — runs LLM eval suite: given task + expected output, scores actual output, returns pass/fail + reasoning
3. `rag_engineer_agent.py` — designs RAG pipelines: chunk strategy, embedding choice, retrieval config, writes retrieval code
4. `changelog_agent.py` — generates CHANGELOG.md from git history, Keep-a-Changelog format
5. `user_story_generator.py` — converts feature requests → Gherkin user stories + acceptance criteria
6. `security_architect.py` — read-only: threat model, auth flow analysis, OWASP architecture review
7. `database_architect.py` — schema design review, index recommendations, migration strategy

**For each agent:**
- Real LangGraph StateGraph with VerificationConfig
- Role file per master template (9 sections)
- Handlers factory in tools.py
- Unit tests

8. Wire all 7 into agents.py dispatch
9. Write `backend/tests/test_day7_agents.py`
10. Update PROJECT.md

**Expected:** 43 total agents, 800+ tests

---

### Gap Day 8 — Redis Queue + Final Audit + v1.0.0
**Goal:** Complete MASTER_PROMPT_PACK Day 7 remainder + full Day 8 audit

**PART A — Redis Queue & Bus:**
1. Install `rq>=1.16` (Redis Queue — Python equivalent of BullMQ)
2. Implement `RQQueueAdapter(QueueAdapter)` using `rq.Queue` + `redis.Redis` — selected when `QUEUE_BACKEND=rq`
3. Implement `RedisStreamsBusAdapter` in `event_bus/bus.py` — `xadd` publish, `xreadgroup` subscribe — selected when `EVENT_BUS_BACKEND=redis`
4. Add `REDIS_URL` to config + `.env.example`
5. Adapter contract tests: same test suite passes against asyncio-mode and rq-mode

**PART B — Concurrency Live Test:**
6. Run 3 concurrent epics on fixture repos, log zero worktree collisions, caps respected

**PART C — Formal Day 8 Audit Deliverables:**
7. `docs/SELLABILITY_GAP.md` — multi-tenancy, org_id scoping, billing, onboarding, per-tenant secrets, SLAs
8. `docs/ADD_A_NEW_AGENT.md` — exact steps: role file → tools → VerificationConfig → register → test × 3. Prove by adding `changelog_writer` end-to-end
9. `docs/reports/FINAL_AUDIT_REPORT.md` — Parts A–D: static sweep, live phase-by-phase, product-grade questions, token efficiency
10. `README.md` — production runbook quality: prerequisites, install, configure, run, how agents work, how to add an agent
11. Final full test suite run → all green
12. `git tag v1.0.0 -m "Production-ready v1.0.0"`

**Expected:** 800+ tests, v1.0.0 tagged, fully audited system

---

## COMPLETION PROJECTIONS

| After | MASTER_PROMPT_PACK | tools_agents.md | Client Milestones |
|-------|-------------------|-----------------|-------------------|
| Current | 85% | 58% | 88% |
| After Gap Day 4 | 88% | 60% | 90% |
| After Gap Day 5 | 89% | 65% | 92% |
| After Gap Day 6 | 90% | 72% | 93% |
| After Gap Day 7 | 91% | 80% | 95% |
| After Gap Day 8 | **98%** | **82%** | **98%** |

*Note: tools_agents.md 100% would require language/framework specialists, Kubernetes agent, CEO/Director agents — these are Phase 2 of the original long-term vision and are not required for a production-ready v1.0.0.*

---

## WHAT IS DONE (for confidence)

### Agents built (36 total):
| Pipeline Agents (6) | Worker Agents - Day 2 (11) | Worker Agents - Day 3 (9) | Support Agents (10) |
|---------------------|---------------------------|---------------------------|---------------------|
| pm, architect, decomposer, planner, coder, executive | bug_fix, security_reviewer, architecture_reviewer, sql_agent, docker_agent, cicd_agent, refactor_agent, readme_agent, api_docs_agent, dependency_agent, monitoring_agent | performance_reviewer, style_reviewer, sprint_planner, business_analyst, migration_agent, schema_agent, ai_engineer, cleanup_agent, tech_debt_agent | manager, devops, research, docs, backend_dev, frontend_dev, qa, reviewer, chat_agent + groq_adapter |

### Infrastructure complete:
- FastAPI + LangGraph + SQLAlchemy + Alembic (8 migrations)
- PostgreSQL checkpointer (pipeline survives restarts)
- Event Bus (Postgres LISTEN/NOTIFY)
- Artifact Store (local disk)
- Engineering Memory (pgvector, similarity search)
- Agent Registry (capability-tag dispatch)
- Cost Controller (estimate + approval threshold)
- Policy Engine v1 + v2 (hardcoded deny + DB-backed rules)
- RBAC (viewer/approver, 403 enforcement)
- Concurrency (asyncio.Semaphore caps, worktree namespacing, file conflict guard)
- Chat Agent (98-tool streaming, SSE, confirmation dialogs)
- Settings UI (API key via browser)
- Repo management UI (clone, activate, per-task)
- 6 frontend pages (tasks, epics, goals, metrics, repo, settings, chat)
- 586 tests passing, mypy --strict clean, TypeScript 0 errors

---

*Plan saved: 2026-07-15. Begin Gap Day 4 when user says "proceed".*
