# Gridiron Developer Department — Master Project Guide & Architecture Reference
> **The Definitive, All-Inclusive Knowledge Encyclopedia: Complete Agent Fleet (72+ Static & Dynamic Meta-Agents), Orchestration Pipeline, Inter-Agent Delegation, Multi-Terminal Intelligence, Memory Hierarchy, 519-Checkpoint 120-Section Audit Ledger, Directory Map, and Q&A Mastery.**
>
> *Author: Bhaskar Barot, AI/ML Engineer*
> *Architecture: LangGraph 1.2.7 + FastAPI + PostgreSQL 16 (pgvector) + Next.js 15 App Router*
> *Audit State (Updated 2026-09-28): 519 Checkpoints Evaluated | 450 YES (95.9% Effective Readiness) | 15 PARTIAL | 0 NO | 4 DEFERRED | 50 SKIP*

---

# Table of Contents
1. [Executive Summary & Core Mission](#1-executive-summary--core-mission)
2. [Why Gridiron Is Different (The Enterprise Department Paradigm)](#2-why-gridiron-is-different-the-enterprise-department-paradigm)
3. [The Technology Stack & Library Ecosystem (Full Matrix)](#3-the-technology-stack--library-ecosystem-full-matrix)
4. [Complete End-to-End Orchestration & Task Lifecycle](#4-complete-end-to-end-orchestration--task-lifecycle)
5. [Complete Fleet Directory: Every Single Agent Explained](#5-complete-fleet-directory-every-single-agent-explained)
   - 5.1 [Special Meta-Agents: Barot Agent, Bhaskar Agent, Sandbox & Pooling](#51-special-meta-agents-barot-agent-bhaskar-agent-sandbox--pooling)
   - 5.2 [Leadership & Core Pipeline Agents (14 Agents)](#52-leadership--core-pipeline-agents-14-agents)
   - 5.3 [Code Quality, Refactoring & Debugging (10 Agents)](#53-code-quality-refactoring--debugging-10-agents)
   - 5.4 [Security & Compliance (5 Agents)](#54-security--compliance-5-agents)
   - 5.5 [Testing & QA Engineering (4 Agents)](#55-testing--qa-engineering-4-agents)
   - 5.6 [Infrastructure, DevOps & Reliability (9 Agents)](#56-infrastructure-devops--reliability-9-agents)
   - 5.7 [Database & Data Architecture (6 Agents)](#57-database--data-architecture-6-agents)
   - 5.8 [Documentation & Communication (7 Agents)](#58-documentation--communication-7-agents)
   - 5.9 [Planning & Estimation (3 Agents)](#59-planning--estimation-3-agents)
   - 5.10 [Fleet Self-Governance & Meta-Auditors (5 Agents)](#510-fleet-self-governance--meta-auditors-5-agents)
   - 5.11 [Developer Experience & Specialized Engineering (9 Agents)](#511-developer-experience--specialized-engineering-9-agents)
   - 5.12 [Automated Platform Documentation Agents (5 Agents)](#512-automated-platform-documentation-agents-5-agents)
6. [Inter-Agent Collaboration, Delegation & Dynamic Behaviors](#6-inter-agent-collaboration-delegation--dynamic-behaviors)
7. [Comprehensive Codebase Directory & File-by-File Map](#7-comprehensive-codebase-directory--file-by-file-map)
8. [Database Architecture & 44 Storage Models](#8-database-architecture--44-storage-models)
9. [All Advanced Features Explained (Deep Technical Mechanics)](#9-all-advanced-features-explained-deep-technical-mechanics)
10. [Terminal Intelligence & Multi-Terminal Execution](#10-terminal-intelligence--multi-terminal-execution)
11. [The 8-Tier Memory Architecture & Knowledge Flow](#11-the-8-tier-memory-architecture--knowledge-flow)
12. [Frontend UI & Interactive Features Walkthrough](#12-frontend-ui--interactive-features-walkthrough)
13. [The 519-Checkpoint 120-Section Production Audit Breakdown](#13-the-519-checkpoint-120-section-production-audit-breakdown)
14. [Master Cheat Sheet: How to Answer Any Question About This Project](#14-master-cheat-sheet-how-to-answer-any-question-about-this-project)

---

# 1. Executive Summary & Core Mission

### What is this project in plain English?
**Gridiron Developer Department is an autonomous, multi-agent software engineering company operating as software.** It takes any plain-English goal or issue description, designs a complete technical architecture, breaks it down into a dependency-ordered directed acyclic graph (DAG) of subtasks, assigns each subtask to the most qualified specialist AI agent from a fleet of 72+ agents, writes the code in isolated Git worktrees, runs actual compiler and test suites inside secure sandboxes, performs automated code and security reviews, updates project documentation, and submits verified GitHub Pull Requests — with human-in-the-loop sign-off gates at every critical juncture.

### Live Codebase Metrics (Verified from Source & Audit):
- **72+ Production Specialist Agents:** Distinct role identities with strictly scoped tool sets, system prompts, and verification contracts.
- **Dynamic Meta-Agents:** Just-in-time capability synthesis (`barot_agent`), dynamic code execution engines (`bhaskar_agent`), and temporary agent pooling (`temporary_agent.py`).
- **170+ Operational Tools:** Concrete executable tools across filesystem, AST code intelligence, execution sandboxes, git operations, browser testing, and external APIs.
- **21 Backend API Router Modules:** Complete async REST API and real-time Server-Sent Events (SSE) streaming engine built in FastAPI.
- **44 Database Tables:** Managed via PostgreSQL 16 + `pgvector` with 39 versioned Alembic migrations.
- **4,000+ Automated Tests:** Rigorous pytest test suites with strict AST event-compliance scans and smoke tests.
- **Audit Verification (519 Checkpoints across 120 Sections):** **450 YES (95.9% Effective Readiness)**, 15 PARTIAL, 0 NO, 4 DEFERRED, 50 SKIP.

---

# 2. Why Gridiron Is Different (The Enterprise Department Paradigm)

### The Single-Agent Dilemma vs. The Multi-Agent Department
Most "AI coding assistants" on the market are single LLM sessions with a bloated system prompt. Asking a single prompt to simultaneously be the Project Manager, Database Architect, Frontend Developer, QA Tester, Security Auditor, and DevOps Engineer causes:
1. **Self-Review Bias:** An LLM that writes a bug will almost never detect its own bug during self-review.
2. **Context Degradation & Hallucination:** Stuffing architectural design, syntax rules, database schemas, and git history into one prompt context window degrades reasoning capacity.
3. **Uncontained Blast Radius:** A single agent with global file and shell access risks accidentally deleting files, dropping tables, or executing unsafe network requests.

### The Gridiron Enterprise Structure:
Gridiron mirrors a Fortune 500 engineering department:
- **Separation of Concerns:** A QA agent (`qa`) can run test suites but has **no file-write tools**. A documentation agent (`docs`) can edit markdown but **cannot alter production code**. A security reviewer (`security_reviewer`) can audit ASTs and scan secrets but **cannot push branches**.
- **Graph-Enforced Truth (Not Model Claims):** The orchestration graph in Python tracks actual OS exit codes. If an agent claims "tests passed" but didn't execute `pytest`, the platform overrides the claim with `tests_passed = False`.
- **Physical Sandboxing:** Commands execute inside isolated, resource-capped Docker containers and ephemeral Git worktrees.

---

# 3. The Technology Stack & Library Ecosystem (Full Matrix)

### Backend Libraries (Python 3.11+)
| Library | Version | Exact Role & Value in Gridiron |
|---|---|---|
| **FastAPI** | `0.139.0` | Powers the async REST API and Server-Sent Events (SSE) streaming endpoints. |
| **Uvicorn** | `0.49.0` | High-throughput ASGI production server. |
| **LangGraph** | `1.2.7` | Core cyclic StateGraph orchestration, human `interrupt()` gates, and durable state checkpointing. |
| **Anthropic SDK** | `0.115.1` | Native integration with Claude 3.5 Sonnet (coding/review) and Claude 3.5/3.7 Haiku (planning/triage). |
| **SQLAlchemy (Async)** | `2.0.51` | Async ORM mapping for all 44 relational database models. |
| **Alembic** | `1.18.5` | Version-controlled database schema migration engine (39 migrations). |
| **Asyncpg / Psycopg3** | `0.31.0` / `3.3.4` | High-speed asynchronous PostgreSQL drivers. |
| **pgvector** | `0.4.2` | Vector similarity extension for semantic code search and engineering memory. |
| **Voyage AI (`voyageai`)** | `0.4.1` | High-accuracy code embedding model (`voyage-code-2` / `voyage-3`). |
| **Tree-Sitter (`tree-sitter`, `tree-sitter-python`, `tree-sitter-javascript`)** | `0.26.0` | Concrete Syntax Tree (CST) and AST parsing for symbol extraction, call graphs, and refactoring. |
| **NetworkX** | `3.6.1` | Directed graph algorithms for subtask topological sorting and cycle detection. |
| **Cryptography (`cryptography`)** | `50.0.0` | AES-CBC Fernet symmetric encryption for the Credential Vault. |
| **Redis & RQ (`rq`, `redis`)** | `2.10.0` / `8.0.1` | Distributed background task queue and Redis Streams event bus. |
| **Playwright** | `1.61.0` | Headless browser automation for live web testing, UI screenshotting, and DOM verification. |
| **OpenTelemetry & Sentry** | `1.44.0` / `2.65.0` | Distributed tracing, runtime metric collection, and error monitoring. |
| **PyJWT & Bcrypt** | `2.13.0` / `5.0.0` | Secure user authentication and password hashing. |
| **Pillow & pdfplumber** | `12.3.0` / `0.11.10` | Multimodal image processing and PDF specification parsing. |
| **psutil** | `7.2.2` | System telemetry collection (CPU, memory, process health). |

### Frontend Libraries (Node 20+ / TypeScript)
| Library | Version | Exact Role & Value in Gridiron |
|---|---|---|
| **Next.js (App Router)** | `15.5.21` | Modern React framework with server components and streaming routes. |
| **React & React DOM** | `19.2.0` | Reactive component UI rendering. |
| **TanStack React Query** | `5.59.0` | Async server state caching, polling, and data synchronization. |
| **@xterm/xterm & @xterm/addon-fit** | `6.0.0` / `0.11.0` | Interactive terminal emulator for live web console and command execution. |
| **TailwindCSS** | `3.4.13` | Utility-first responsive styling and dark mode UI design. |
| **Zod** | `3.23.8` | Strict runtime TypeScript schema validation for API payloads. |

---

# 4. Complete End-to-End Orchestration & Task Lifecycle

```
[ User Input / Goal ] (with optional Mockup Images & Target Repo)
        │
        ▼
[ Blank Repo Check ] ── (Zero-commit repo?) ──► [ Bootstrap Scaffold Sequence ]
        │
        ▼
[ 1. PM Agent ] ──► Produces PM Brief (Goals, Acceptance Criteria, Scope)
        │
        ▼
[ 2. Architect Agent ] ──► Produces Technical Plan (Impacted Files, Risks, Architecture)
        │
        ▼
[ 3. Decomposer Agent ] ──► Produces Subtasks (DAG with depends_on relationships)
        │
        ▼
[ 4. LangGraph Interrupt ] ──► ⏸️ PAUSES FOR HUMAN REVIEW (Approve / Edit Steps / Reject)
        │
        ├─────────────────────────────┐
 [ Human Rejects ]             [ Human Approves / Edits ]
        │                             │
        ▼                             ▼
  Status: "rejected"           [ 5. Manager Subtask Execution Loop ]
                                      │
                                      ▼
                      [ Topological Sort Dispatcher ]
                                      │
                      ┌───────────────┴───────────────┐
                      ▼                               ▼
              [ Subtask 1 (DB) ]             [ Subtask 2 (API) ]
                      │                               │
         [ Advisory File Lock Acquired ] [ Advisory File Lock Acquired ]
                      │                               │
         [ Git Worktree Created: ]       [ Git Worktree Created: ]
         [ /worktrees/task-1-sub-1 ]     [ /worktrees/task-1-sub-2 ]
                      │                               │
         [ Developer Agent Writes Code ] [ Developer Agent Writes Code ]
                      │                               │
         [ QA Agent Runs Pytest/Linter ] [ QA Agent Runs Pytest/Linter ]
                      │                               │
         [ Graph Verification Check ]    [ Graph Verification Check ]
                      │                               │
         [ Reviewer Agent Diffs Code ]   [ Reviewer Agent Diffs Code ]
                      │                               │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      [ 6. Failure Recovery Ladder ] (If tests fail, self-heal up to 7 rungs)
                                      │
                                      ▼
                      [ 7. Docs Agent Updates README & Changelog ]
                                      │
                                      ▼
                      [ 8. Git Commit to Worktree Branch ]
                                      │
                                      ▼
                      [ 9. Human Final Sign-Off Gate ]
                                      │
                                      ▼
                      [ 10. Automated GitHub PR & Push via API ]
```

---

# 5. Complete Fleet Directory: Every Single Agent Explained

### 5.1 Special Meta-Agents: Barot Agent, Bhaskar Agent, Sandbox & Pooling

#### 1. `barot_agent` — Just-in-Time Meta-Agent ("The Brain")
- **File:** `backend/app/agents/barot_agent.py`
- **Role:** When `fleet_manager.select()` encounters a task requiring a capability that no static agent possesses, `barot_agent` steps in. It analyzes the capability gap, uses Claude to generate a minimal, safe tool profile, and commands `TemporaryAgentPool` (`app/agents/temporary_agent.py`) to spawn a short-lived `temporary_agent`.
- **Safety Invariant:** `barot_agent` declares `capabilities=[]` and denylists delegation tools so it can never recursively select itself.

#### 2. `bhaskar_agent` — Dynamic Code & Tool Synthesis Engine
- **File:** `backend/app/agents/bhaskar_agent.py`
- **Role:** The internal execution engine powering `bhaskar_tool` (`app/tools/agents/bhaskar_tool.py`). When an agent needs to perform an ad-hoc computation or custom API query that no static tool handles, `bhaskar_agent` researches via `web_search`, writes a self-contained Python script, tests it inside `bhaskar_sandbox.py`, and returns verified output.
- **Safety Invariant:** Excludes `bhaskar_tool` from its own tool list, backed by a `ContextVar` (`bhaskar_agent_active`) recursion guardrail.

#### 3. `bhaskar_sandbox` — Hardened Python Sandbox
- **File:** `backend/app/agents/bhaskar_sandbox.py`
- **Role:** An isolated subprocess runner for synthesized scripts with memory limits (`256MB`), execution timeouts (`30s`), stripped environment variables (preventing credential theft), and non-root execution.

#### 4. `temporary_agent` — Dynamic Agent Pooling & Lifecycle Manager
- **File:** `backend/app/agents/temporary_agent.py`
- **Role:** Manages the lifecycle of dynamically synthesized agents. Spawns isolated worker threads, enforces bounded execution, and garbage-collects temporary resources once the gap task completes.

---

### 5.2 Leadership & Core Pipeline Agents (14 Agents)
1. **`pm` (Project Manager):** Analyzes requirements, user goals, and produces structured PM briefs with acceptance criteria (`pm.py`).
2. **`architect`:** Reads codebase structure and produces technical implementation plans, file impact lists, and risk assessments (`architect.py`).
3. **`decomposer`:** Breaks architectural plans into typed subtasks with strict dependency ordering (`depends_on`) (`decomposer.py`).
4. **`planner`:** General-purpose planning agent for ad-hoc implementation plans (`planner.py`).
5. **`executive`:** Translates high-level corporate objectives into structured epics and strategic roadmaps (`executive.py`).
6. **`manager`:** The master orchestrator. Dispatches subtasks, coordinates dev/QA/review cycles, and handles lifecycle state transitions (`manager.py`).
7. **`coder`:** Full-stack developer capable of implementing backend and frontend code in git worktrees (`coder.py`).
8. **`backend_dev`:** Specialist in server-side logic, APIs, FastAPI, database access, and async workers (`backend_dev.py`).
9. **`frontend_dev`:** Specialist in React, Next.js, TypeScript, TailwindCSS, and client-side state (`frontend_dev.py`).
10. **`qa`:** Executes test commands (`pytest`, `npm test`, `mypy`, `ruff`) in worktrees. Test-only permissions (no file writes) (`qa.py`).
11. **`reviewer`:** Performs senior-level code reviews on git diffs, checking for logic flaws and anti-patterns (`reviewer.py`).
12. **`chat_agent`:** Interactive streaming conversational agent that can explore repos, read files, and run tools dynamically (`chat_agent.py`).
13. **`research`:** Conducts technical research using web search and repository scans to answer technical unknowns (`research.py`).
14. **`docs`:** Generates changelogs, updates documentation, and synchronizes READMEs after epic completion (`docs.py`).

---

### 5.3 Code Quality, Refactoring & Debugging (10 Agents)
15. **`code_quality_agent`:** Audits code for maintainability, cyclomatic complexity, and design smells (`code_quality_agent.py`).
16. **`style_reviewer`:** Enforces linting, PEP8/Prettier conventions, and import hygiene (read-only) (`style_reviewer.py`).
17. **`architecture_reviewer`:** Analyzes import graphs, circular dependencies, layer violations, and dead code (`architecture_reviewer.py`).
18. **`performance_reviewer`:** Identifies N+1 database queries, slow loops, memory leaks, and missing indexes (`performance_reviewer.py`).
19. **`tech_debt_agent`:** Tracks lint violations, test coverage gaps, and oversized modules (`tech_debt_agent.py`).
20. **`refactor_agent`:** Refactors legacy code with mandatory before-and-after test execution to ensure zero behavior drift (`refactor_agent.py`).
21. **`cleanup_agent`:** Scans for unused imports, dead functions, and orphan files, requiring confirmation before removal (`cleanup_agent.py`).
22. **`debugger_agent`:** Diagnoses stack traces, analyzes git blame, identifies root causes, and recommends fixes (`debugger_agent.py`).
23. **`bug_fix`:** Specialized in reproducing bugs with failing tests, writing the fix, and verifying tests pass (`bug_fix.py`).
24. **`code_explainer_agent`:** Produces clear, multi-level explanations of complex code for onboarding and documentation (`code_explainer_agent.py`).

---

### 5.4 Security & Compliance (5 Agents)
25. **`security_reviewer`:** Scans code for hardcoded secrets, SQL injection, XSS, auth bypasses, and insecure configurations (`security_reviewer.py`).
26. **`security_architect`:** Performs STRIDE threat modeling and OWASP Top 10 architecture reviews (`security_architect.py`).
27. **`compliance_agent`:** Audits repositories for regulatory compliance (GDPR, SOC2, HIPAA, PCI-DSS data handling) (`compliance_agent.py`).
28. **`dependency_security_agent`:** Runs live dependency vulnerability audits (`pip-audit`, `npm audit`) to detect CVEs (`dependency_security_agent.py`).
29. **`env_checker_agent`:** Detects undocumented environment variables, missing `.env.example` keys, and leaked secrets (`env_checker_agent.py`).

---

### 5.5 Testing & QA Engineering (4 Agents)
30. **`test_writer_agent`:** Generates comprehensive unit and integration test suites based on real AST signatures (`test_writer_agent.py`).
31. **`test_coverage_agent`:** Analyzes `coverage.py` and `lcov` reports to highlight uncovered edge cases and branches (`test_coverage_agent.py`).
32. **`evaluation_agent`:** Runs LLM evaluation benchmarks and scores prompt outputs against ground truth datasets (`evaluation_agent.py`).
33. **`load_test_agent`:** Generates `k6` and `Locust` load testing scripts modeled on real OpenAPI route schemas (`load_test_agent.py`).

---

### 5.6 Infrastructure, DevOps & Reliability (9 Agents)
34. **`docker_agent`:** Generates and optimizes Dockerfiles and docker-compose files (modifications require human approval) (`docker_agent.py`).
35. **`cicd_agent`:** Manages GitHub Actions and CI/CD workflow configurations (requires human sign-off) (`cicd_agent.py`).
36. **`infra_agent`:** Audits Terraform, Kubernetes manifests, and cloud configs for security gaps and missing resource limits (`infra_agent.py`).
37. **`devops`:** Runs safe health-check commands, inspects server statuses, and reports operational health (`devops.py`).
38. **`monitoring_agent`:** Queries CPU, memory, latency, and error metrics from live system telemetry (`monitoring_agent.py`).
39. **`incident_responder_agent`:** Triages production outages, determines blast radius, and writes step-by-step mitigation plans (`incident_responder_agent.py`).
40. **`rollback_agent`:** Analyzes git logs and migration histories to produce safe, automated rollback strategies (`rollback_agent.py`).
41. **`runbook_generator_agent`:** Writes operational runbooks and disaster recovery guides from service source code (`runbook_generator_agent.py`).
42. **`slo_agent`:** Formulates Service Level Objectives (SLOs) and Service Level Indicators (SLIs) from metric configurations (`slo_agent.py`).

---

### 5.7 Database & Data Architecture (6 Agents)
43. **`database_architect`:** Designs normalized relational schemas, recommends indexing strategies, and creates DDLs (`database_architect.py`).
44. **`schema_agent`:** Inspects live database schemas and tables (`schema_agent.py`).
45. **`sql_agent`:** Writes and validates complex SQL queries against live schemas (`sql_agent.py`).
46. **`migration_agent`:** Writes, inspects, and validates Alembic / Prisma database migration scripts (`migration_agent.py`).
47. **`data_pipeline_agent`:** Designs and reviews ETL/ELT pipelines, data transformations, and batch jobs (`data_pipeline_agent.py`).
48. **`rag_engineer_agent`:** Designs Retrieval-Augmented Generation (RAG) architectures: chunking, embeddings, and vector DBs (`rag_engineer_agent.py`).

---

### 5.8 Documentation & Communication (7 Agents)
49. **`readme_agent`:** Writes high-quality project READMEs by analyzing actual code structure and dependencies (`readme_agent.py`).
50. **`api_docs_agent`:** Extracts route handlers and Pydantic schemas to generate OpenAPI/Swagger documentation (`api_docs_agent.py`).
51. **`changelog_agent`:** Formats git commit histories into Keep-a-Changelog standard release notes (`changelog_agent.py`).
52. **`release_notes_agent`:** Compiles release notes comparing tags, highlighting breaking changes and new features (`release_notes_agent.py`).
53. **`onboarding_agent`:** Creates developer onboarding guides from setup scripts and project configurations (`onboarding_agent.py`).
54. **`user_story_generator`:** Converts product feature descriptions into Gherkin-formatted acceptance tests (`Given/When/Then`) (`user_story_generator.py`).
55. **`business_analyst`:** Analyzes business requirements, edge cases, and user personas (`business_analyst.py`).

---

### 5.9 Planning & Estimation (3 Agents)
56. **`sprint_planner`:** Breaks epics into sprint-ready stories with complexity estimates and velocity forecasting (`sprint_planner.py`).
57. **`cost_estimator_agent`:** Calculates implementation time and forecasts LLM token expenditure for proposed tasks (`cost_estimator_agent.py`).
58. **`spike_agent`:** Executes time-boxed research spikes to validate third-party libraries and technical feasibility (`spike_agent.py`).

---

### 5.10 Fleet Self-Governance & Enhancement Agents (5 Self-Improvement Agents)

These 5 specialized meta-agents form the **Fleet Self-Improvement Subsystem**. They monitor the entire platform, give work advice, detect bugs, audit performance, and generate structured **Enhancement Requests** visible in the `/fleet` web dashboard for human review and one-click application:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    THE 5 FLEET ENHANCEMENT AGENTS (DAY 9)                      │
│                                                                                 │
│  [ agent_advisor ]                [ agent_debugger ]                            │
│  Reviews orchestration accuracy   Diagnoses fleet errors from real audit logs   │
│                                                                                 │
│  [ agent_performance_reviewer ]   [ quality_auditor ]                           │
│  Tracks tokens, latency, cost     Audits code, security, UI & lint standards    │
│                                                                                 │
│                          [ knowledge_curator ]                                  │
│                          Deduplicates & promotes engineering memory             │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼ (Autonomous SCAN Phase)
                     ┌───────────────────────────────────────┐
                     │ Files EnhancementRequest in Database  │
                     │ (Title, Category, Evidence, Diff)     │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼ (Broadcast via SSE)
                     ┌───────────────────────────────────────┐
                     │ /fleet Dashboard UI in Next.js        │
                     │ (Shows Proposal + Diff + Risk Level)  │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼ (Human Decision)
                          ┌──────────────┴──────────────┐
                          ▼                             ▼
                 [ User Rejects ]              [ User Approves ]
                  (Terminal Exit)                       │
                                                        ▼ (APPLY Phase)
                                        ┌───────────────────────────────┐
                                        │ Agent applies code/prompt fix │
                                        │ Runs verification tests       │
                                        │ Commits git SHA with rollback │
                                        └───────────────────────────────┘
```

#### Detailed Breakdown of the 5 Enhancement Agents:

1. **`agent_advisor` (`agent_advisor.py`):**
   - **Purpose:** Reviews orchestration correctness across the fleet. It analyzes recent task runs to determine: *Did the orchestrator pick the right agent(s)? Was any agent over-provisioned or under-qualified? Did a task need multiple agents but only got one?*
   - **Tools Used:** `task_history_query`, `fleet_metrics_read`, `audit_log_read`, `submit_enhancement_request`, `record_learning`.
   - **Two-Phase Mode:** Purely advisory (scan-only by design) — it files structured enhancement proposals in the UI for pipeline routing adjustments.

2. **`agent_debugger` (`agent_debugger.py`):**
   - **Purpose:** Detects failing agents, crash loops, and platform runtime bugs by inspecting real audit-trail logs and error events.
   - **Tools Used (Scan Phase):** `audit_log_read`, `read_file`, `search_code`.
   - **Tools Used (Apply Phase):** `edit_file`, `write_file`, `run_tests`, `git_commit_change`.
   - **Workflow:** In the Scan Phase, it discovers a bug (e.g., a regex flaw in a tool parser) and files an enhancement request with evidence. When approved in the `/fleet` UI, it executes its Apply Phase, edits the code, runs pytest to verify the fix, and commits the change.

3. **`agent_performance_reviewer` (`agent_performance_reviewer.py`):**
   - **Purpose:** Analyzes real runtime performance telemetry across all 72 agents (p50/p95 latency, token consumption, error rates, tool call volume).
   - **Tools Used (Scan Phase):** `fleet_metrics_read`, `read_file`, `search_code`.
   - **Tools Used (Apply Phase):** `edit_file`, `write_file`, `run_tests`, `git_commit_change`.
   - **Workflow:** Detects slow or token-heavy prompts and generates optimized prompt versions or caching enhancements in the UI.

4. **`quality_auditor` (`quality_auditor.py`):**
   - **Purpose:** Conducts holistic audits of the platform for security vulnerabilities, UI styling regressions, test coverage holes, and code formatting violations.
   - **Tools Used (Scan Phase):** `secrets_scan`, `run_linter`, `read_file`, `search_code`.
   - **Tools Used (Apply Phase):** `edit_file`, `write_file`, `run_tests`, `git_commit_change`.
   - **Workflow:** Files specific, one-issue-per-request enhancement proposals to keep platform quality pristine without human engineers needing to manually audit.

5. **`knowledge_curator` (`knowledge_curator.py`):**
   - **Purpose:** Curates and cleans the fleet's persistent engineering memory store (`MemoryEmbedding` and `VersionedLesson`).
   - **Tools Used (Scan Phase):** `memory_search`, `read_file`.
   - **Tools Used (Apply Phase):** `memory_curate_write`, `memory_archive`, `record_learning`.
   - **Workflow:** Deduplicates near-identical lessons, recategorizes outdated rules, merges conflicting takeaways via LLM synthesis, and promotes high-value patterns from DRAFT to PUBLISHED.

#### The Enhancement Request UI & Lifecycle (`/fleet` Dashboard):
- **Database Table:** `enhancement_requests` (`models.py:838`) stores every proposal with fields: `id`, `agent_name`, `title`, `description`, `category`, `priority`, `evidence`, `status` (`pending`, `approved`, `rejected`, `applied`, `failed`), `files_touched`, `commit_sha`, and `trace_id`.
- **API Endpoints:**
  - `GET /api/fleet/requests` — List and filter enhancement proposals.
  - `POST /api/fleet/requests/{id}/approve` — Human approval kicks off background Apply Phase.
  - `POST /api/fleet/requests/{id}/reject` — Marks proposal as rejected.
  - `GET /api/fleet/requests/stream` — Real-time Server-Sent Events (SSE) broadcasting new enhancement suggestions directly to the UI.
- **Rollback Protection (`enhancement_rollback.py`):** Every code-changing enhancement records its Git commit SHA. If platform benchmarks or tests decline post-application, the system provides an automated rollback mechanism to revert the change safely.

---

### 5.11 Developer Experience & Specialized Engineering (9 Agents)
64. **`devex_agent`:** Audits developer friction, local setup scripts, and environment ergonomics (`devex_agent.py`).
65. **`accessibility_agent`:** Scans frontend code for WCAG 2.1 AA compliance, ARIA attributes, and keyboard navigation (`accessibility_agent.py`).
66. **`pair_programmer_agent`:** Explains code step-by-step and guides interactive implementation sessions (`pair_programmer_agent.py`).
67. **`localization_agent`:** Detects hardcoded UI strings, missing translation keys, and i18n date/currency formatting issues (`localization_agent.py`).
68. **`feature_flag_agent`:** Scans codebase for stale feature flags and flags without clear ownership (`feature_flag_agent.py`).
69. **`api_designer_agent`:** Designs REST and GraphQL API contracts with standard naming and status code standards (`api_designer_agent.py`).
70. **`version_manager_agent`:** Audits package dependencies for major version upgrades and breaking changes (`version_manager_agent.py`).
71. **`ai_engineer`:** Implements machine learning models, inference scripts, and AI pipelines (`ai_engineer.py`).
72. **`dependency_agent`:** Checks package registries for outdated dependencies and security patches (`dependency_agent.py`).

---

### 5.12 Automated Platform Documentation Agents (5 Agents)
73. **`agent_roster_doc_agent`:** Automatically generates and synchronizes documentation for the entire 72-agent fleet (`agent_roster_doc_agent.py`).
74. **`architecture_doc_agent`:** Generates high-level system architecture diagrams and documentation (`architecture_doc_agent.py`).
75. **`tool_catalog_doc_agent`:** Automatically compiles markdown documentation for all 170+ operational tools (`tool_catalog_doc_agent.py`).
76. **`deployment_guide_doc_agent`:** Generates deployment guides across Docker, Kubernetes, Vercel, and Railway (`deployment_guide_doc_agent.py`).
77. **`migration_guide_doc_agent`:** Generates guides for database schema migrations and breaking API changes (`migration_guide_doc_agent.py`).

---

# 6. Inter-Agent Collaboration, Delegation & Dynamic Behaviors

Gridiron is not just a collection of isolated agents; it is an interconnected collaborative network:

### 1. Inter-Agent Delegation (`app/agents/delegation.py` & `delegate_to_agent`)
- When an agent encounters a specialized requirement (e.g., `backend_dev` needs a security audit or complex SQL query), it can call `delegate_to_agent`.
- **Safety Matrix:** Delegation is governed by an allowed-target matrix (e.g., `coder → security_reviewer` is allowed, `qa → coder` is denied).
- **Cycle Detection & Depth Limiting:** Enforces `max_depth = 3` and cycle detection so agents cannot infinitely delegate in loops.
- **Budget Inheritance:** Delegated sub-agents inherit remaining token budgets and execution timeouts from the parent run.

### 2. Guidance & Clarification Requests (`app/agents/guidance.py` & `request_guidance`)
- When requirements are ambiguous or a breaking change is detected, an agent can pause and invoke `request_guidance`.
- The system registers a clarification request in `PendingApproval`, notifying the human user in the UI to answer before the agent proceeds.

### 3. Dynamic Subtask Creation (`app/pipeline/dynamic_subtasks.py` & `propose_subtask`)
- If a developer agent discovers unforeseen work mid-execution (e.g., discovering an unindexed table or missing migration), it calls `propose_subtask`.
- The orchestrator validates the request against project budget, checks for duplicate work, updates the DAG, and inserts the subtask dynamically into the manager queue.

### 4. Conflict Resolution & Merge Guards (`app/agents/conflict_resolution.py`)
- Analyzes parallel diffs and resolves overlapping file edits using AST merge strategies and LLM conflict reconciliation.

### 5. Role & Intent Detection (`app/agents/role_detection.py`)
- Automatically analyzes user task prompts to classify intent and match the optimal agent capability without requiring manual assignment.

### 6. User Sentiment & Tone Adaptation (`app/agents/user_sentiment.py`)
- Monitors user messages for urgency, satisfaction, or frustration, dynamically adjusting response detail, safety gates, and escalation thresholds.

---

# 7. Comprehensive Codebase Directory & File-by-File Map

```
/home/pc-117/Documents/CRR2906/
├── apps/
│   └── web/                                → Next.js 15 App Router Frontend
│       ├── app/                            → Application Pages & Routing
│       │   ├── page.tsx                    → Home Dashboard
│       │   ├── tasks/                      → Task Management (List, Detail, Create, PR)
│       │   ├── chat/                       → Interactive Agentic Repository Chat
│       │   ├── console/                    → Web Terminal & Command Console
│       │   ├── approvals/                  → Human-in-the-Loop Approval Center
│       │   ├── fleet/                      → Fleet OS Dashboard & Self-Improvement
│       │   ├── epics/ & goals/             → High-level Epics & Goals Tracking
│       │   ├── repo/                       → Repository Explorer & Worktree Manager
│       │   ├── cost/ & metrics/            → Token Costs & System Performance Metrics
│       │   └── settings/                   → Credential Vault & System Settings
│       └── components/                     → Reusable UI Components
│           ├── PipelineView.tsx            → Interactive LangGraph Planning Visualizer
│           ├── TerminalPanel.tsx           → Live Xterm.js Terminal Console
│           ├── DiffViewer.tsx              → Side-by-Side Code Diff Inspection
│           ├── NewTaskForm.tsx             → Task Creation Form with Multimodal Image Picker
│           └── NavBar.tsx                  → Global Navigation Header
│
├── backend/                                → Python 3.11+ / FastAPI / LangGraph Backend
│   ├── app/
│   │   ├── main.py                         → FastAPI application entry point, lifespan, background loops
│   │   ├── config.py                       → Pydantic Settings (93 configuration keys)
│   │   ├── api/                            → 21 FastAPI Router Modules
│   │   │   ├── tasks.py                    → Task lifecycle, planning triggers, PR creations, images
│   │   │   ├── approvals.py                → Human approval gate endpoints (approve/reject/edit)
│   │   │   ├── activity.py                 → Real-time Server-Sent Events (SSE) streaming
│   │   │   ├── chat.py                     → Interactive repo chat agent streaming
│   │   │   ├── console.py & terminal.py    → Terminal process spawning and web console
│   │   │   ├── fleet_dashboard.py          → Fleet OS enhancement requests and benchmarks
│   │   │   ├── settings.py                 → Credential Vault & custom secrets management
│   │   │   ├── specialized_agents.py       → Direct sync/async execution of all 72 individual agents
│   │   │   ├── repo.py, epics.py, goals.py → Repository, epic, and goal management
│   │   │   └── memory.py, audit.py, auth.py→ Memory search, security audit logs, JWT auth
│   │   │
│   │   ├── agents/                         → Agent Definitions & Core Execution Engine
│   │   │   ├── base_graph.py               → Base LangGraph builder, VerificationConfig, memory hooks
│   │   │   ├── manager.py                  → Subtask execution loop, QA/Review coordination, retries
│   │   │   ├── barot_agent.py              → Dynamic meta-agent ("the brain") for capability gaps
│   │   │   ├── bhaskar_agent.py            → Dynamic code synthesis engine for bhaskar_tool
│   │   │   ├── bhaskar_sandbox.py          → Hardened Python sandbox execution environment
│   │   │   ├── temporary_agent.py          → Dynamic agent pooling and lifecycle management
│   │   │   ├── delegation.py               → Inter-agent task delegation and safety matrix
│   │   │   ├── guidance.py                 → Human/agent guidance and clarification requests
│   │   │   ├── conflict_resolution.py      → Multi-agent merge and plan conflict reconciliation
│   │   │   ├── role_detection.py           → Prompt intent and role classification
│   │   │   ├── user_sentiment.py           → User satisfaction and tone monitoring
│   │   │   ├── chat_agent.py               → Multi-turn conversational repo agent
│   │   │   ├── tools.py                    → 170+ tool implementations and tool execution dispatch
│   │   │   ├── tool_security.py            → Secret redaction, citation verification, path checks
│   │   │   └── [72 agent files].py         → Individual agent definitions and CONTRACT configs
│   │   │
│   │   ├── pipeline/                       → Orchestration & Concurrency Engine
│   │   │   ├── graph.py                    → LangGraph StateGraph (PM → Architect → Decomposer → interrupt)
│   │   │   ├── bootstrap.py                → Blank repository detection & auto-scaffolding
│   │   │   ├── dispatcher.py               → Topological subtask dependency dispatcher
│   │   │   ├── file_locks.py               → Advisory database-backed file locking for parallel tasks
│   │   │   ├── conflict_guard.py           → Multi-task file overlap detection
│   │   │   ├── dynamic_subtasks.py         → Mid-execution subtask proposal & validation
│   │   │   └── queue_adapter.py            → Asyncio vs. Redis/RQ queue selector
│   │   │
│   │   ├── fleet/                          → Fleet OS Subsystem
│   │   │   ├── capability_registry.py      → Master registry of all 72 agents & capabilities
│   │   │   ├── model_router.py             → Dynamic LLM routing (Claude Haiku/Sonnet, Groq, OpenAI)
│   │   │   ├── benchmark_manager.py        → 7-objective performance baseline tracking
│   │   │   ├── budget_manager.py           → Per-run and daily token cost enforcement
│   │   │   ├── prompt_registry.py          → Versioned prompt lifecycle (draft → review → deploy)
│   │   │   ├── versioned_memory.py         → Lessons learned with LLM merge-on-conflict
│   │   │   ├── failure_ladder.py           → 7-rung deterministic failure recovery engine
│   │   │   ├── circuit_breaker.py          → Resilient circuit breaker on Anthropic/LLM APIs
│   │   │   └── tool_manifest.py            → Comprehensive tool catalog with risk levels
│   │   │
│   │   ├── policy/                         → Safety & Sandboxing Engine
│   │   │   ├── engine.py                   → Command denylist & path traversal guards
│   │   │   └── sandbox.py                  → Docker container sandbox with cgroup resource limits
│   │   │
│   │   ├── security/                       → Security & Credential Management
│   │   │   └── credential_vault.py         → Fernet AES encryption at rest for API keys & secrets
│   │   │
│   │   ├── repo_tools/                     → Repository Intelligence
│   │   │   ├── ast_engine.py               → Tree-Sitter AST & symbol parser
│   │   │   ├── cross_file_graph.py         → Symbol call graph & dependency mapper
│   │   │   ├── context_builder.py          → Smart context assembler for LLM prompts
│   │   │   └── worktree.py                 → Git worktree lifecycle management
│   │   │
│   │   ├── memory/                         → Engineering Memory Store
│   │   │   ├── store.py                    → Project-scoped pgvector semantic memory engine
│   │   │   ├── consolidation.py            → Background clustering and memory consolidation
│   │   │   └── analytics.py                → Memory reuse metrics and utility analytics
│   │   │
│   │   └── db/                             → Database Layer
│   │       ├── models.py                   → 44 SQLAlchemy ORM database models
│   │       ├── repository.py               → Data access object (DAO) CRUD methods
│   │       └── session.py                  → Async database engine & connection pool
│   │
│   ├── roles/                              → 72 Markdown Agent System Prompts (`pm.md`, etc.)
│   ├── migrations/                         → 39 Alembic database migration scripts
│   └── tests/                              → 4,000+ Pytest automated test suites
│
├── docker-compose.yml                      → Multi-container orchestration (DB, Redis, Backend, Web)
├── run.sh                                  → Unified startup script for backend, frontend, and database
└── package.json & pnpm-workspace.yaml      → Monorepo workspace configuration
```

---

# 8. Database Architecture & 44 Storage Models

All models inherit from SQLAlchemy `DeclarativeBase` in `backend/app/db/models.py`:

| Model / Table Name | Core Purpose & Fields |
|---|---|
| **`DevTask`** | Core task entity: status, title, description, branch_name, pr_url, pr_status, repo_id, parent_task_id, costs. |
| **`TaskLog`** | Append-only structured event logs: task_id, level, stage, message, data (JSONB). |
| **`TaskImage`** | Attached multimodal screenshots/mockups: task_id, image_bytes, media_type, file_name. |
| **`AgentRun`** | Individual agent invocations: task_id, agent_type, model_id, status, tokens_in, tokens_out, cost_estimate, trace_id. |
| **`Subtask`** | Ordered steps from Decomposer: task_id, index, title, description, agent_type, status, depends_on, files_to_edit. |
| **`PipelineState`** | Checkpoint state of the LangGraph planning pipeline: stage, thread_id, checkpoint_id. |
| **`IndexedFile`** | Repository files scanned: repo_id, path, hash, language, line_count, ast_tree. |
| **`Symbol`** | Extracted code functions/classes: file_id, name, kind (function/class), start_line, end_line. |
| **`CallEdge`** | Call-graph relationships: caller_symbol_id, callee_symbol_id, call_type. |
| **`MemoryEmbedding`** | `pgvector` semantic engineering memory: project_id, content, vector (1536/1024 dims), metadata. |
| **`VersionedLesson`** | Managed fleet lessons: category, content, version, status (`DRAFT`, `PUBLISHED`, `SUPERSEDED`, `ARCHIVED`). |
| **`PendingApproval`** | Human approval gates: approval_type (`plan`, `diff`, `git_push`, `prompt`), payload, status. |
| **`EpicFileLock`** | Advisory file locks: file_path, subtask_id, task_id, locked_at, expires_at (prevents race conditions). |
| **`EpicScratchpad`** | Shared persistent scratchpad notes across subtasks during epic execution. |
| **`EnhancementRequest`** | Fleet self-improvement proposals from meta-agents: title, description, target_agent, diff, status. |
| **`AgentBenchmark`** | Performance baselines across 7 objectives (hallucination, verification, tool accuracy, speed, cost). |
| **`PromptVersion`** | Versioned role prompts: agent_name, version, prompt_text, status (`draft`, `approved`, `deployed`). |
| **`SystemSetting`** | System config keys and Credential Vault encrypted secrets (Fernet cipher). |
| **`Artifact`** | Generated artifacts (diffs, reports, test logs) stored in database or S3. |
| **`TaskControlFlag`** | In-process execution flags for Pause / Stop / Resume / Cancel. |
| **`User` & `UserRole`** | RBAC authentication: username, hashed_password, email, role permissions. |
| **`Event` & `FailedEvent`** | Fleet event bus audit trail and dead-letter queue. |
| **Score Tables** | `ArchitectureScore`, `AgentsScore`, `ToolsScore`, `PromptsScore`, `SecurityScore`, `TestScore`. |

---

# 9. All Advanced Features Explained (Deep Technical Mechanics)

### 1. Graph-Enforced Verification (Anti-Hallucination Engine)
- **Problem:** LLMs will fabricate claims that test suites succeeded even when code fails to compile.
- **Solution:** `app/agents/base_graph.py` implements a hardcoded `VerificationConfig`. The LangGraph execution state tracks tool runs in `state["verification"]`.
- When an agent uses `edit_file` or `write_file`, `tests_passed` is reset to `False`.
- `tests_passed` only becomes `True` when `run_tests` executes and returns exit code 0.
- When an agent calls `submit_result`, the Python graph overrides the LLM's return dictionary with the verified boolean flags.

### 2. Real Docker Command Sandboxing
- **Problem:** Agents running raw bash commands could compromise the host server.
- **Solution:**
  1. **Policy Denylist:** `app/policy/engine.py` blocks dangerous command strings (`rm -rf`, `docker push`, `npm publish`, `.env*` reads).
  2. **Container Sandbox:** `app/policy/sandbox.py` routes high-risk commands into an isolated Docker container with 512MB RAM, 1 CPU core, and 128 PIDs limits.
  3. Only the task's Git worktree is mounted. If Docker is offline, the command **fails closed** and refuses to execute on the host.

### 3. Git Worktree Isolation & Multi-Repo Workspaces
- `app/repo_tools/worktree.py` isolates each subtask inside an independent `git worktree` at `/tmp/gridiron/worktrees/task-{id}-sub-{index}`.
- Live codebase files on the `main` branch are never touched directly during development.
- If a subtask aborts, the worktree folder and temporary branch are deleted with zero residual side effects on the repository.

### 4. 7-Rung Failure Recovery Ladder
When QA tests or linters fail, `app/fleet/failure_ladder.py` triggers an escalating recovery ladder:
1. **Rung 1 — Retry with Error Context:** Re-feed the compiler/linter error back to the developer agent.
2. **Rung 2 — Tool Parameter Adjustment:** Alter search tools or broaden AST lookups.
3. **Rung 3 — Codebase Re-index & Context Refresh:** Invalidate AST caches and reload symbol graphs.
4. **Rung 4 — Re-Plan Subtask:** Call the `planner` agent to restructure the subtask strategy.
5. **Rung 5 — Alternate Specialist Dispatch:** Switch agent (e.g., from `coder` to specialized `bug_fix`).
6. **Rung 6 — Human Clarification Escalation:** Create a `PendingApproval` asking the human for guidance.
7. **Rung 7 — Safe Abort & Rollback:** Cleanly delete the worktree, release file locks, mark task `failed`, and alert the team.

### 5. Project-Scoped Memory with LLM Conflict-Merging
- Memories are vectorized using Voyage AI (`voyage-code-2`) and stored in PostgreSQL `pgvector`.
- **Project Scoping:** Every memory is partitioned by `project_id`/`repo_id` to prevent architectural leakage between distinct client codebases.
- **Merge-on-Conflict (`versioned_memory.py`):** When a new lesson conflicts with a prior lesson, Claude analyzes both and merges them into a single, unified updated lesson (`SUPERSEDED` provenance).

### 6. Zero-Trust Fernet Credential Vault
- Secrets and API tokens are encrypted at rest using AES Fernet keys (`app/security/credential_vault.py`).
- In production (`DEPLOYMENT_ENV=production`), the backend hard-refuses to boot if `CREDENTIAL_ENCRYPTION_KEY` is missing.
- When agents run commands, secrets are injected only into the child process environment and automatically masked (`_redact_secrets_in_text`) from logs, databases, and SSE streams.

### 7. Blank Repository Auto-Bootstrap
- If an empty repo (0 commits) is targeted, `app/pipeline/bootstrap.py` detects this and runs:
  1. `git init` and initial file touch.
  2. Architect agent designs project scaffolding.
  3. Coder agent writes baseline files (`package.json`, `main.py`, `.gitignore`).
  4. Commits `Initial project scaffold by Gridiron` to `main`.
  5. The standard PM → Architect → Decomposer pipeline then starts cleanly.

### 8. Multimodal Visual Input Pipeline
- Users can attach UI mockups, Figma screenshots, or bug images in `NewTaskForm.tsx`.
- Images are encoded to base64 and stored in `TaskImage`.
- Fed directly to Anthropic Claude 3.5/3.7 Sonnet for the `pm`, `architect`, `frontend_dev`, and `reviewer` agents as native `ImageBlockParam` content blocks.

### 9. Advisory Database File Locks (Concurrency Protection)
- When multiple subtasks run in parallel, two agents might attempt to edit the same file (e.g., `app/main.py`).
- `app/pipeline/file_locks.py` uses `EpicFileLock` to acquire database-level leases on target file paths. If a file is locked by Subtask A, Subtask B safely waits until Subtask A commits and unlocks.

### 10. Fleet OS Self-Improvement Subsystem
- Meta-agents (`agent_debugger`, `agent_performance_reviewer`, `quality_auditor`) scan audit logs every few hours.
- If an agent consistently fails on a specific tool or task type, the meta-agents create an `EnhancementRequest` proposing prompt tweaks or tool additions.
- The human administrator reviews and approves these self-improvements in the `/fleet` dashboard.

---

# 10. Terminal Intelligence & Multi-Terminal Execution

Gridiron provides an enterprise terminal management subsystem:
1. **Interactive Web Terminal Console (`TerminalPanel.tsx`):**
   - Built on `@xterm/xterm` and `@xterm/addon-fit`.
   - Connects to backend PTY processes via async endpoints (`/api/terminal`, `/api/console`).
2. **Background Process Registry (`bg_process_registry.py`):**
   - Tracks long-running background servers (e.g., `npm run dev`, `uvicorn`, Docker containers).
   - Monitors streaming output, health status, PID tracking, and graceful termination.
3. **Output Parsers:**
   - Intelligent parsers for pytest (`parse_test_output`), type-checkers (`mypy`, `tsc`), linters (`ruff`, `eslint`), and Docker build logs.
4. **Hanging Process Detection:**
   - Detects commands exceeding execution timeouts or waiting on unsupplied stdin, killing the hung process and returning actionable diagnostic reports.

---

# 11. The 8-Tier Memory Architecture & Knowledge Flow

Gridiron implements eight distinct memory tiers across agents:
1. **Working Memory:** In-memory LangGraph dictionary during an agent turn (`state["messages"]`, `state["verification"]`).
2. **Session Memory:** Checkpointed in PostgreSQL via `AsyncPostgresSaver`, surviving server restarts and network interruptions.
3. **Shared Memory (`EpicScratchpad`):** Inter-agent scratchpad where subtasks share intermediate outputs during an epic.
4. **Project Memory:** Vectorized codebase architecture notes, coding standards, and directory conventions scoped by `project_id`.
5. **Long-Term Memory (`MemoryEmbedding`):** pgvector semantic embeddings of past solutions, design decisions, and lessons learned.
6. **Procedural Memory:** Operational workflows, migration procedures, and deployment runbooks.
7. **Failure Memory:** Catalog of past test failures, compiler errors, and the exact fixes that resolved them.
8. **Knowledge Memory:** Domain facts, third-party library constraints, and API specifications.

---

# 12. Frontend UI & Interactive Features Walkthrough

1. **Dashboard (`/`):** High-level view of active tasks, system health, fleet agent status, and recent activity.
2. **Task Creation (`/tasks` + `NewTaskForm.tsx`):**
   - Goal description, target repository selection, execution mode (`full` PM pipeline vs `simple` direct coding).
   - Drag-and-drop multimodal image attachment.
3. **Pipeline Visualizer (`PipelineView.tsx`):**
   - Live visual diagram of the LangGraph state machine.
   - Shows current stage (PM → Architect → Decomposer → Review → Manager → Subtasks).
4. **Approval Center (`/approvals`):**
   - Shows pending human-in-the-loop decisions.
   - Plan approval with interactive subtask editing (edit title, description, or remove steps).
   - Code diff review before git push.
5. **Interactive Console & Terminal (`/console` + `TerminalPanel.tsx`):**
   - Built with `@xterm/xterm`. Allows direct interaction with repository worktree terminals.
6. **Fleet Management (`/fleet`):**
   - Overview of all 72 agents, capability tags, model mappings, and enhancement requests.
7. **Interactive Repository Chat (`/chat`):**
   - Chat with the entire codebase. The chat agent dynamically scans AST, runs searches, and explains logic.
8. **Real-Time Stream Feed (`/stream`):**
   - Live Server-Sent Events (SSE) showing agent thinking tokens, tool invocations, file modifications, and terminal outputs.

---

# 13. The 519-Checkpoint 120-Section Production Audit Breakdown

Compiled directly from `bhaskar_next/GRIDIRON_PARTIAL_NO_IMPLEMENTATION_PLAN.txt` (updated 2026-09-28):

### Overall Audit Score (519 Checkpoints across 120 Sections):
- **YES (Production Ready):** **450 (86.7% raw / 95.9% effective readiness)**
- **PARTIAL (Needs Work / Scoped):** **15 (2.9%)**
- **NO (Missing / Real Gap):** **0 (0%)** (all 14 original NO items resolved: 10 closed to YES, 2 scoped in PARTIAL #227 & #443, 2 moved to DEFERRED #171 & #494).
- **DEFERRED (Explicit User Decision):** **4 (0.8%)** (#169, #171, #494, #511 — multi-instance distributed registry/tenancy).
- **SKIP (Deliberate Boundaries / Out of Scope):** **50 (9.6%)** (e.g. AWS/K8s direct live deploy execution which is a human action forever).

### Key Audit Sections Summary:
- **Section 1: Repository Execution (11/11 YES):** Clones into user folders, worktree containment, session manager, Docker terminal, virtualenv activation, safe shell execution, Windows CI support.
- **Section 17: Terminal Intelligence (9/9 YES):** Streaming output monitoring, completion/failure detection, hanging process guards, log and pytest output parsing.
- **Section 58: Multi-Terminal & Parallel Execution (5/5 YES):** Concurrent shell registry, fan-out execution, background/foreground distinction, terminal cleanup.
- **Section 18 & 59: Coding & Multi-File Operations (13/13 YES):** Multi-file read/write, AST refactoring, comment and formatting preservation, restricted file protection, architectural consistency.
- **Section 2: Complete Orchestration (12/13 YES, 1 SKIP):** Defined PM→Architect entry path, DAG subtask dependency handling, advisory file locking, human interrupt gates, dynamic subtasks crash recovery.
- **Section 3 & 4: Agent & Tool Selection (12/13 YES, 1 SKIP):** Capability matching, historical performance weighting, multi-tool turn execution, memory-outcome attribution, dynamic tool filtering.
- **Section 5 & 120: Memory System (20/20 YES):** All 8 memory tiers implemented, pgvector persistence, token context compression, lifecycle aging, quality validation feedback, consolidation.
- **Section 7: 20-Capability Audit (20/20 YES):** Smart planning, context awareness, long-term memory, self-critique, failure recovery ladder, credential encryption, cross-agent collaboration, architecture awareness.

### Honest Status of the 15 PARTIAL Items:
1. **#71 (Rollback, automatic):** Manual operator rollback is production-ready; scheduled auto-rollback on regression is documented for future wiring.
2. **#150 (Communication/Collaboration as dedicated skill):** Intentional boundary — criteria kept in role definitions rather than a separate vague agent.
3. **#162 (Modularity of `tools.py`):** Substantially split (`tools.py` reduced from 12,500+ to ~7,340 lines across domain submodules).
4. **#196 & #198 (Guardian Tier Tools & Centralized Monitoring):** Intentionally shared tool infrastructure (reuse over duplication).
5. **#227 (Take over task / edit plan):** Edit/reject subtask at human_review interrupt is production-ready and tested; full mid-DAG checkpoint jump is scoped.
6. **#255 (Edit very large files safely):** Streaming ranged-read is production-ready; write streaming is scheduled.
7. **#291 (AWS deploy execution):** Deliberate safety boundary — deployment is strictly a human action.
8. **#300 (Merge conflict auto-resolution):** Deliberate safety boundary — high-risk conflicts pause for human judgment.
9. **#329 (Central governance beyond security policy):** Blocked pending user definition of company-specific coding rules.
10. **#377 (Concurrent tenant isolation):** Blocked on future multi-tenancy data model.
11. **#414 (Aggregate quality score):** 7/9 categories verified; documentation/performance await external signals.
12. **#427 (Queue reordering):** Priority-bucketing queue is production-ready; in-place reordering is intentional no-change.
13. **#443 (Agent hallucination & memory leaks):** Hallucination detection is fully production-ready; sustained app-load profiling is out-of-scope.
14. **#509 (Overall AI software company readiness):** Tracks the 4 deferred multi-instance items.

### The 4 DEFERRED Items (Multi-Instance Distributed Scaling):
- **#169, #171, #494, #511:** In-memory single-process registries and distributed dispatch semaphores across multiple backend instances. Postponed by explicit decision since Gridiron currently runs as a dedicated single-instance engineering department backend.

---

# 14. Master Cheat Sheet: How to Answer Any Question About This Project

Use this quick-reference guide to confidently answer any technical question:

### Q1: "What makes Gridiron different from single coding assistants like Cursor or Claude Code?"
> **Answer:** "Cursor and Claude Code are single-agent models with large prompts. Gridiron is an **autonomous software engineering department**. It organizes work across 72+ specialist agents (PM, Architect, Developers, QA, Security Reviewer, DevOps) coordinated by LangGraph. Furthermore, Gridiron uses **Graph-Enforced Verification** — it verifies tool exit codes in Python code, meaning agents cannot hallucinate that tests passed."

### Q2: "What is `barot_agent` and how does dynamic agent synthesis work?"
> **Answer:** "`barot_agent` is the just-in-time meta-agent ('the brain'). When the orchestrator needs a capability not present in the static fleet of 72 agents, `barot_agent` analyzes the gap, designs a minimal tool profile, and commands `TemporaryAgentPool` to synthesize, execute, and destroy a short-lived `temporary_agent` with strict safety boundaries."

### Q3: "What is `bhaskar_agent` and `bhaskar_sandbox`?"
> **Answer:** "`bhaskar_agent` is the internal engine powering `bhaskar_tool`. When an agent needs an ad-hoc computation or custom API integration not covered by built-in tools, `bhaskar_agent` researches via web search, writes self-contained Python code, executes it inside `bhaskar_sandbox` (a hardened, memory-capped, credential-scrubbed sandbox), and returns verified results."

### Q4: "How do multiple agents work in parallel without merge conflicts?"
> **Answer:** "Gridiron enforces two safeguards: (1) **Git Worktrees:** Each subtask executes in an isolated worktree (`git worktree add -b`). (2) **Advisory Database File Locks:** `app/pipeline/file_locks.py` acquires database leases (`EpicFileLock`) on target files, ensuring parallel agents never write to the same file at the same time."

### Q5: "How does the system recover when code fails tests?"
> **Answer:** "It uses a deterministic **7-Rung Failure Recovery Ladder**: (1) Retry with compiler errors → (2) Tool adjustment → (3) Context refresh → (4) Re-plan subtask → (5) Switch to specialized bug fix agent → (6) Request human guidance → (7) Safe rollback and worktree deletion."

### Q6: "How are credentials and security handled?"
> **Answer:** "Credentials are encrypted at rest with AES Fernet keys in `CredentialVault`. Commands are checked against a policy denylist and executed inside ephemeral, resource-capped Docker containers. Secrets are dynamically scrubbed from all terminal outputs, databases, and streaming feeds."

### Q7: "What was the result of the 519-checkpoint production audit?"
> **Answer:** "Gridiron achieved an **effective production readiness score of 95.9%** (450 YES out of 469 relevant checkpoints, 0 NO items remaining). The remaining items consist of 15 honestly scoped or safety-bounded PARTIAL items, 4 multi-instance scaling items explicitly DEFERRED by design, and 50 out-of-scope SKIP items (such as direct automated cloud deployments, which remain human-gated by design)."

---
*End of Master Guide. Keep this document as the definitive technical reference for the Gridiron Developer Department platform.*
