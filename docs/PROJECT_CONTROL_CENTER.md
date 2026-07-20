# Project Control Center — Live State
Last updated: 2026-07-20 (full audit + gap-closure + Day 7 + Day 8 session)

---

## Agent Production Readiness

| Agent | Flags | CONTRACT | Role Prompt | VerificationConfig | Tests | Status |
|-------|-------|----------|-------------|--------------------|-------|--------|
| architect | ✅ | ✅ | ✅ | ✅ `submit_architect_plan→plan_submitted` | ✅ | ✅ PRODUCTION |
| decomposer | ✅ | ✅ | ✅ | ✅ `submit_subtasks→subtasks_submitted` | ✅ | ✅ PRODUCTION |
| planner | ✅ | ✅ | ✅ | ✅ `submit_plan→plan_submitted` | ✅ | ✅ PRODUCTION |
| pm | ✅ | ✅ | ✅ | ✅ `submit_brief→brief_submitted` | ✅ | ✅ PRODUCTION |
| backend_dev | ✅ | ✅ | ✅ | ✅ `bash→checks_run, git_diff→diff_checked` | ✅ | ✅ PRODUCTION |
| frontend_dev | ✅ | ✅ | ✅ | ✅ `bash→checks_run, git_diff→diff_checked` | ✅ | ✅ PRODUCTION |
| coder | ✅ | ✅ | ✅ | ✅ `bash→checks_run, git_diff→diff_checked` | ✅ | ✅ PRODUCTION |
| reviewer | ✅ | ✅ | ✅ | ✅ `git_diff→diff_reviewed` | ✅ | ✅ PRODUCTION |
| qa | ✅ | ✅ | ✅ | ✅ `bash→tests_run` | ✅ | ✅ PRODUCTION |
| devops | ✅ | ✅ | ✅ | ✅ `bash→checks_run` | ✅ | ✅ PRODUCTION |
| research | ✅ | ✅ | ✅ | ✅ `submit_research→research_submitted` | ✅ | ✅ PRODUCTION |
| executive | ✅ | ✅ | ✅ | N/A — no tools (pure LLM), legitimate | ✅ | ✅ PRODUCTION |
| docs | ✅ | ✅ | ✅ | ✅ `write_file→docs_written` | ✅ | ✅ PRODUCTION |
| bug_fix | ✅ | ✅ | ✅ | ✅ `run_tests→tests_passed, git_diff→diff_checked` | ✅ | ✅ PRODUCTION |
| security_reviewer | ✅ | ✅ | ✅ | ✅ `secrets_scan→scan_ran` | ✅ | ✅ PRODUCTION |
| architecture_reviewer | ✅ | ✅ | ✅ | ✅ `import_graph→import_graph_ran` | ✅ | ✅ PRODUCTION |
| sql_agent | ✅ | ✅ | ✅ | ✅ `inspect_schema→schema_inspected` | ✅ | ✅ PRODUCTION |
| docker_agent | ✅ | ✅ | ✅ | ✅ `docker_build→build_ran` | ✅ | ✅ PRODUCTION |
| cicd_agent | ✅ | ✅ | ✅ | ✅ `bash→lint_ran` | ✅ | ✅ PRODUCTION |
| refactor_agent | ✅ | ✅ | ✅ | ✅ `run_tests→tests_passed` | ✅ | ✅ PRODUCTION |
| readme_agent | ✅ | ✅ | ✅ | ✅ `read_file→files_read` | ✅ | ✅ PRODUCTION |
| api_docs_agent | ✅ | ✅ | ✅ | ✅ `find_route→routes_found` | ✅ | ✅ PRODUCTION |
| dependency_agent | ✅ | ✅ | ✅ | ✅ `read_file→manifest_read` | ✅ | ✅ PRODUCTION |
| monitoring_agent | ✅ | ✅ | ✅ | ✅ `cpu_usage→metrics_collected` | ✅ | ✅ PRODUCTION |
| performance_reviewer | ✅ | ✅ | ✅ | ✅ `explain_query→query_explained` | ✅ | ✅ PRODUCTION |
| style_reviewer | ✅ | ✅ | ✅ | ✅ `run_linter→lint_ran` | ✅ | ✅ PRODUCTION |
| sprint_planner | ✅ | ✅ | ✅ | ✅ `estimate_complexity→complexity_estimated` | ✅ | ✅ PRODUCTION |
| business_analyst | ✅ | ✅ | ✅ | ✅ `read_file→requirements_read` (tag deduped 2026-07-20) | ✅ | ✅ PRODUCTION |
| migration_agent | ✅ | ✅ | ✅ | ✅ `inspect_schema→schema_inspected` | ✅ | ✅ PRODUCTION |
| schema_agent | ✅ | ✅ | ✅ | ✅ `inspect_schema→schema_inspected` | ✅ | ✅ PRODUCTION |
| ai_engineer | ✅ | ✅ | ✅ | ✅ `run_python_snippet/bash→code_tested` | ✅ | ✅ PRODUCTION |
| cleanup_agent | ✅ | ✅ | ✅ | ✅ `dead_code_detect→dead_code_scanned` | ✅ | ✅ PRODUCTION |
| tech_debt_agent | ✅ | ✅ | ✅ | ✅ `run_linter→lint_ran` | ✅ | ✅ PRODUCTION |
| release_notes_agent | ✅ | ✅ | ✅ | ✅ `git_log→git_log_read` | ✅ | ✅ PRODUCTION |
| evaluation_agent | ✅ | ✅ | ✅ | ✅ `run_python_snippet→eval_run` | ✅ | ✅ PRODUCTION |
| rag_engineer_agent | ✅ | ✅ | ✅ | ✅ `read_file→codebase_read` | ✅ | ✅ PRODUCTION |
| changelog_agent | ✅ | ✅ | ✅ | ✅ `generate_changelog→git_log_read` (tag deduped 2026-07-20) | ✅ | ✅ PRODUCTION |
| user_story_generator | ✅ | ✅ | ✅ | ✅ `read_file→codebase_read` | ✅ | ✅ PRODUCTION |
| security_architect | ✅ | ✅ | ✅ | ✅ `read_file→codebase_read` | ✅ | ✅ PRODUCTION |
| database_architect | ✅ | ✅ | ✅ | ✅ `read_file→schema_read` | ✅ | ✅ PRODUCTION |
| manager | N/A (orchestrator, never calls run_agent_graph) | ✅ | ✅ | N/A — legitimate | ✅ | ✅ PRODUCTION |
| chat_agent | N/A (interactive session, not run_agent_graph) | ✅ *(added 2026-07-20)* | ✅ | ✅ `read_file/search_code→read` *(added 2026-07-20)* | ✅ | ✅ PRODUCTION |
| code_explainer_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| code_quality_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| accessibility_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| api_designer_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| compliance_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| cost_estimator_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| data_pipeline_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| debugger_agent | ✅ | ✅ | ✅ | ✅ `read_file/git_blame→read` | ✅ | ✅ PRODUCTION |
| dependency_security_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| devex_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| env_checker_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| feature_flag_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| incident_responder_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| infra_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| load_test_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| localization_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| onboarding_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| pair_programmer_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| rollback_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| runbook_generator_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| slo_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| spike_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| test_coverage_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| test_writer_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| version_manager_agent | ✅ | ✅ | ✅ | ✅ `read_file→read` | ✅ | ✅ PRODUCTION |
| groq_adapter | N/A (infra utility, not a task agent) | N/A *(per plan's own Day 6 note)* | N/A | N/A | — | ✅ registry-only, by design |

**67/67 real task agents in `capability_registry`. 68/68 names (incl. groq_adapter) in `agent_models.json`. Day 7 hardening: COMPLETE — see 2026-07-20 session in PROJECT.md.**

*5 fleet-level agents (agent_performance_reviewer, agent_debugger, agent_advisor, knowledge_curator, quality_auditor): not yet built — Day 9.*

---

## Fleet OS Health

| Component | Status | Notes |
|-----------|--------|-------|
| capability_registry | ✅ 67 agents registered | All Day 1–6 batches confirmed via live import + registry inspection (not just doc claims) |
| agent_registry | ✅ SLEEP/IDLE/RUNNING states wired | `complete_task()` → AgentState.SLEEP after every run; sleep-wiring regression from `dc27e1e` fixed 2026-07-20 |
| Event bus | ✅ 8 typed events | TaskCreated, TaskStarted, TaskCompleted, TaskFailed, ReviewRequested, LessonPublished, HealthUpdated, MemoryCreated |
| fleet_checkpoint | ✅ save/restore/rollback + trace_id | trace_id stored in metadata |
| Fleet OS flags (20 capabilities) | ✅ All default True in base_graph.py | enable_planning, enable_memory, enable_reflection, enable_lesson |
| memory_hook_node repo-context injection | ✅ FIXED 2026-07-20 | Was calling a nonexistent `scanner.build_repo_index` (real name: `index_repository`), silently swallowed by a broad except — capability #15 (Architecture Awareness) never actually fired until this fix |
| Role prompts (v2.0: 11-section global + 7 role-specific) | ✅ 67/67 files verified | Superset of the plan's original 9-section template — see Day 8 note below |
| **P1 Activity Stream UI** | ✅ Day 5A complete | SSE streaming: thinking/tool_call/file_edit/terminal events + Stop+Resume |
| **P2 Model Router** | ✅ Day 5A complete | `agent_models.json` covers all 68 names; wired into `run_agent_graph()` |
| **P3 Repo Console** | ✅ Day 5A complete | Clone→Work→Push web console; `git_service.py`; workspace scoping |
| Groq test shim | ✅ TEMPORARY, isolated | `USE_GROQ=true` in `.env` is for local manual/dev-server use only; `tests/conftest.py` forces `USE_GROQ=false` for the unit suite (fixed 2026-07-20 — was silently making real network calls for ~2000 tests) |
| Budget manager | ❌ Not built | Day 10 |
| Benchmark manager | ❌ Not built | Day 10 |
| Prompt registry | ❌ Not built | Day 11 |
| Regression detector | ❌ Not built | Day 11 |
| Tool discovery | ❌ Not built | Day 10 |
| Versioned memory | ❌ Not built | Day 11 |

---

## Gap Summary (as of 2026-07-20)

| Gap | Status | Day |
|-----|--------|-----|
| Fleet OS flags default True | ✅ CLOSED | Day 0 |
| Agent SLEEP transition (Gap 7) | ✅ CLOSED (regression fixed 2026-07-20) | Day 0 |
| trace_id in fleet_checkpoint (Gap 10) | ✅ CLOSED | Gap fix 2026-07-17 |
| Role prompts all files | ✅ CLOSED (v2.0 superset, verified 2026-07-20) | Gap fix 2026-07-17 + v2.0 2026-07-20 |
| AGENT_CONTRACT + _register() Day 1 agents | ✅ CLOSED | Sessions 1–4 |
| AGENT_CONTRACT + _register() Day 2 agents | ✅ CLOSED | Day 2 |
| AGENT_CONTRACT Day 3 batch | ✅ CLOSED | Day 3 |
| AGENT_CONTRACT Day 4 batch | ✅ CLOSED | Day 4 |
| P1 Activity Stream UI | ✅ CLOSED | Day 5A |
| P2 Central Model Router | ✅ CLOSED | Day 5A |
| P3 Repo Console | ✅ CLOSED | Day 5A |
| AGENT_CONTRACT Day 5B batch (9 agents) | ✅ CLOSED (chat_agent gap found + fixed 2026-07-20) | Day 5B + gap fix |
| AGENT_CONTRACT Day 6 batch (17 + groq_adapter) | ✅ CLOSED | Day 6 |
| Capability tag duplicates (business_analyst/user_story_generator, changelog_agent/release_notes_agent) | ✅ CLOSED | Gap fix 2026-07-20 |
| Groq-bypass sleep-wiring regression + test-suite network-call leak | ✅ CLOSED | Gap fix 2026-07-20 |
| ReviewResult isinstance bug (importlib.reload class-identity) | ✅ CLOSED | Gap fix 2026-07-20 |
| chat_agent._BACKGROUND_PROCESSES runtime bug | ✅ CLOSED | Gap fix 2026-07-20 |
| VerificationConfig hardening all agents (Day 7) | ✅ CLOSED | Day 7 — 2026-07-20 |
| Role prompt 9-section verification + durable test coverage (Day 8) | ✅ CLOSED | Day 8 — 2026-07-20 |
| 5 new fleet agents | ❌ OPEN | Day 9 |
| budget_manager + benchmark_manager + tool_discovery | ❌ OPEN | Day 10 |
| prompt_registry + regression_detector + versioned_memory | ❌ OPEN | Day 11 |
| End-to-end pipeline smoke test | ❌ OPEN | Day 12 |

---

## Open Issues

- [ ] mypy `--strict`: 34 pre-existing errors, 0 new. 18 in `app/repo_tools/browser_driver.py` (predates Fleet Days, unrelated to fleet work). 7 in `base_graph.py` (LangGraph `StateGraph` generic/overload typing — known library-stub limitation). Remainder scattered (`tools.py`, `agent_result.py`, `audit_log.py`, `config.py`, `jwt.py`).
- [ ] 55 skipped tests (pre-existing — unbuilt frontend features) + 17 deselected (real-LLM Groq tests, rate-limited on free tier, pending until `ANTHROPIC_API_KEY` available — see memory `pending_anthropic_tests`).
- [ ] Fleet work has been happening directly on `main` rather than the plan's prescribed `fleet-enhancement-day0` branch (Pre-Day 0A). Process deviation, not a functional bug — flagged for awareness, not blocking.

---

## Completed Days

| Day | Date | Tests | Key Deliverable |
|-----|------|-------|-----------------|
| Sessions 1–4 | 2026-07-16 | 123/123 | 13 agents migrated to run_agent_graph + AGENT_CONTRACT |
| Day 0 | 2026-07-16 | 1525+ | 20 Fleet OS capabilities enabled fleet-wide |
| Day 1 | 2026-07-17 | +17 | 13 agents: fleet flags + VerificationConfig + role prompts |
| Day 2 | 2026-07-17 | +81 | 11 agents: AGENT_CONTRACT + _register() + role prompts |
| Gap Fixes | 2026-07-17 | — | trace_id checkpoint, VerificationConfig, role prompts 67/67, PCC + arch graphs |
| Day 3 | 2026-07-17 | +76 | 9 agents: AGENT_CONTRACT + _register() + fleet flags + VerificationConfig |
| Day 4 | 2026-07-17 | +158 | 8 agents: AGENT_CONTRACT + _register() + fleet flags + VerificationConfig |
| Day 5A | 2026-07-17 | +53 | P1 Streaming UI, P2 Model Router, P3 Repo Console — platform foundations |
| Day 5B | 2026-07-17 | +97 | 8/9 agents AGENT_CONTRACT (chat_agent gap found + closed 2026-07-20) |
| Day 6 | ~2026-07-18/19 | — | 17 agents + groq_adapter AGENT_CONTRACT batch |
| v2.0 Role Prompts | 2026-07-20 | 2260 | DRY `_GLOBAL_STANDARDS.md` + 7 role-specific sections, all 67 files |
| **Full Audit + Gap-Closure** | **2026-07-20** | **2254/2254, 0 failed** | Found + fixed 11 real gaps (see PROJECT.md session log): chat_agent migration, groq_adapter registration, Groq-bypass regression + test-network-leak, repo-context injection bug, duplicate capability tags, test-order pollution, ReviewResult reload bug, chat_agent background-process bug, 13 mypy fixes |
| **Day 7 — VerificationConfig Hardening** | **2026-07-20** | **2254/2254** | 0 empty configs (except legitimate executive/manager), 0 duplicate tags, 0 dead enforce keys, 0 `verify_agent_contract()` violations |
| **Day 8 — Role Prompt Verification** | **2026-07-20** | **2399/2399** | Read roo-code's prompt-section pattern first (REPO-FIRST); verified all 9 plan-required sections present (verbatim/near-verbatim) in `_GLOBAL_STANDARDS.md`; wrote 145 new durable tests (`test_day8_role_prompts.py`) — 0 prior test coverage existed for role-prompt structure |
