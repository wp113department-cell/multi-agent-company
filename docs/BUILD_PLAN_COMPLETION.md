# Gridiron Developer Department — Completion Build Plan
**Created:** 2026-07-14  
**Goal:** Build all remaining tools and agents to match `files/tools_agents.md` spec  
**Starting state:** 69 CHAT_TOOLS · 15 agents · 378 tests passing · mypy clean

---

## How to execute this plan

Each session: read this file → pick the next unchecked phase → implement → test → check off → commit → update PROJECT.md.

**Rules (same as always):**
- Every new tool → added to `CHAT_TOOLS` + `make_chat_handlers()` + `_execute_tool()` in chat_agent.py
- Every new agent → `backend/app/agents/<name>.py` + role prompt in `backend/roles/<name>.md`
- Every phase → `pytest backend/tests/ -q` must stay green + `mypy --ignore-missing-imports` clean
- End of each day → commit + append results to PROJECT.md

---

## DAY 1 — Complete the Core Tool Layer

**Target:** ~40 new tools added. All fundamentals complete.

---

### Phase 1A — Real AST Engine (Python `ast` module)
**File:** `backend/app/repo_tools/ast_engine.py` (new utility module)  
**Adds tools:** `parse_ast`, `import_graph`, `call_graph`, `dead_code_detect`, `circular_dep_detect`, `rename_symbol`  
**Upgrades:** `list_functions` and `list_classes` to use `ast.parse` instead of grep

**Implementation notes:**
- Use `ast.walk(ast.parse(source))` — no extra packages needed, stdlib only
- `parse_ast(path)` → returns top-level structure: imports, classes, functions, constants
- `import_graph(path)` → returns dict: `{module: [symbols]}` for all imports in a file
- `call_graph(path, function_name)` → find all function calls inside a named function
- `dead_code_detect(directory)` → grep for defined functions that have 0 references elsewhere (heuristic)
- `circular_dep_detect(directory)` → parse all imports recursively, detect cycles
- `rename_symbol(path, old_name, new_name, file_pattern)` → sed-style replace across all matching files
- Upgrade `list_functions` handler: use `ast.parse` for .py files, keep grep fallback for .ts/.tsx

**Tests to write:** `tests/test_ast_engine.py` — at least 15 tests covering parse_ast, import_graph, dead code, rename_symbol

**Checklist:**
- [ ] Create `backend/app/repo_tools/ast_engine.py` with `ASTEngine` class
- [ ] Add `parse_ast`, `import_graph`, `call_graph`, `dead_code_detect`, `circular_dep_detect`, `rename_symbol` to CHAT_TOOLS
- [ ] Add handlers in `make_chat_handlers()` and `_execute_tool()`
- [ ] Upgrade `list_functions` / `list_classes` to use ast.parse for .py files
- [ ] Write `tests/test_ast_engine.py` (15+ tests)
- [ ] `pytest tests/test_ast_engine.py -v` → all pass
- [ ] `mypy app/repo_tools/ast_engine.py --ignore-missing-imports` → clean
- [ ] Commit: `feat: real AST engine — parse_ast, call_graph, dead_code_detect, rename_symbol`

---

### Phase 1B — Missing Git Tools
**Adds tools:** `git_rebase`, `git_cherry_pick`  
**File:** existing `tools.py` + `chat_agent.py`

**Implementation notes:**
- `git_rebase(onto, interactive=False)` — for interactive, block and suggest using bash instead (no TTY)
- `git_cherry_pick(commit_hash, no_commit=False)` — `git cherry-pick [--no-commit] <hash>`
- Both need confirmation if `--hard` or force flags involved

**Tests:** 4 tests in `tests/test_chat_tools.py` (append)

**Checklist:**
- [ ] Add `_GIT_REBASE_TOOL` and `_GIT_CHERRY_PICK_TOOL` spec dicts
- [ ] Add to CHAT_TOOLS list
- [ ] Add sync handlers in `make_chat_handlers()`
- [ ] Add async dispatch in `_execute_tool()`
- [ ] Write 4 tests
- [ ] Commit: `feat: git_rebase + git_cherry_pick tools`

---

### Phase 1C — Terminal Extras
**Adds tools:** `read_output`, `run_node`, `run_script`, `docker_build`, `docker_restart`  
**File:** existing `tools.py` + `chat_agent.py`

**Implementation notes:**
- `read_output(pid, lines=50)` — read stdout/stderr of background process from `_BACKGROUND_PROCESSES` dict. Use `proc.stdout.readlines()` with a non-blocking read (set `proc.stdout` to non-blocking via `fcntl`)
- `run_node(code, timeout=30)` — `node -e <code>` (check node is available)
- `run_script(path, interpreter="auto")` — auto-detect .py/.js/.sh and run with appropriate interpreter
- `docker_build(context, tag, dockerfile=None)` — `docker build -t <tag> [options] <context>`
- `docker_restart(container)` — `docker restart <container>`

**Tests:** 8 tests

**Checklist:**
- [ ] Add 5 tool specs + CHAT_TOOLS entries
- [ ] Add handlers
- [ ] Write 8 tests
- [ ] Commit: `feat: read_output, run_node, run_script, docker_build, docker_restart`

---

### Phase 1D — Smart Search Tools
**Adds tools:** `find_route`, `find_api`, `find_sql`, `find_test`, `find_config`  
**File:** existing `tools.py` + `chat_agent.py`

**Implementation notes:**
- `find_route(method=None, path_pattern=None)` — grep for `@router.get/post/put/delete` and `@app.route` patterns. Parse FastAPI route decorators
- `find_api(name)` — find API endpoint definitions (decorators, function names, return types)
- `find_sql(keyword=None)` — grep for SQL strings: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, SQLAlchemy `text()`, `session.execute()`
- `find_test(function_name)` — find all test functions that test a given function name (by keyword matching: `test_<function_name>` or `def test_...<function_name>`)
- `find_config(key)` — search for a config key in .env.example, config.py, settings files, YAML/TOML

**Tests:** 10 tests

**Checklist:**
- [ ] Add 5 tool specs
- [ ] Add handlers (grep-based, all under 30 lines each)
- [ ] Write 10 tests
- [ ] Commit: `feat: find_route, find_api, find_sql, find_test, find_config`

---

### Phase 1E — Monitoring Tools
**Adds tools:** `cpu_usage`, `memory_usage`, `disk_usage`, `health_check`, `task_progress`  
**File:** existing `tools.py` + `chat_agent.py`

**Implementation notes:**
- `cpu_usage()` — `psutil.cpu_percent(interval=1)` OR `subprocess.run(["top", "-bn1"])` — use stdlib if psutil not available
- `memory_usage()` — `psutil.virtual_memory()` OR parse `/proc/meminfo`
- `disk_usage(path="/")` — `shutil.disk_usage(path)` (stdlib, no extra deps)
- `health_check(service=None)` — check if backend (localhost:8000/health), DB (psql ping), Redis (redis-cli ping) are up
- `task_progress(task_id=None, limit=10)` — query `task_logs` table via psql for recent task status

**Tests:** 8 tests

**Checklist:**
- [ ] Add 5 tool specs
- [ ] Add handlers (prefer stdlib `shutil.disk_usage`, `/proc/meminfo` for memory, `subprocess` for CPU)
- [ ] Write 8 tests
- [ ] Commit: `feat: monitoring tools — cpu/memory/disk/health_check/task_progress`

---

### Phase 1F — Editing Completions
**Adds tools:** `replace_class`, `undo_changes`, `generate_patch`, `read_binary_file`  
**File:** existing `tools.py` + `chat_agent.py`

**Implementation notes:**
- `replace_class(path, class_name, new_code)` — same logic as `replace_function` but finds `class <name>:` blocks
- `undo_changes(path)` — `git checkout -- <path>` (restores to last commit, requires confirmation)
- `generate_patch(path_a_content, path_b_content, filename)` — use `difflib.unified_diff()` (stdlib) to produce a unified diff string
- `read_binary_file(path, encoding="hex")` — read file bytes, return as hex string or base64 (for inspecting non-text files)

**Tests:** 8 tests

**Checklist:**
- [ ] Add 4 tool specs
- [ ] Add handlers
- [ ] Write 8 tests
- [ ] Commit: `feat: replace_class, undo_changes, generate_patch, read_binary_file`

---

### Phase 1G — Database Extras
**Adds tools:** `explain_query`, `run_migration`, `seed_database`  
**File:** existing `tools.py` + `chat_agent.py`

**Implementation notes:**
- `explain_query(query)` — prepend `EXPLAIN ANALYZE` to the query and run via psql
- `run_migration(direction="upgrade", revision="head")` — `alembic upgrade head` or `alembic downgrade -1` from `backend/` dir; ALWAYS requires user confirmation before running
- `seed_database(script=None)` — run `backend/scripts/seed.py` if it exists, or a custom script path; requires confirmation

**Tests:** 6 tests

**Checklist:**
- [ ] Add 3 tool specs
- [ ] Add handlers (run_migration MUST go through confirmation gate)
- [ ] Write 6 tests
- [ ] Commit: `feat: explain_query, run_migration (with confirmation), seed_database`

---

### Day 1 End Goal
- **New tools added:** ~40
- **Total CHAT_TOOLS:** ~109
- **Tests:** 450+ passing
- **mypy:** clean
- Commit: `day-1/tool-completion`

---

## DAY 2 — Agent Expansion

**Target:** 12 new agents built and wired. All have: role prompt (.md), LangGraph node, tools scoped correctly, tests.

---

### Phase 2A — Bug Fix Agent
**File:** `backend/app/agents/bug_fix.py`  
**Role:** `backend/roles/bug_fix.md`

**What it does:** Receives a bug report (error message, traceback, or failing test output). Uses `analyze_error`, `find_references`, `search_code`, `read_file`, `edit_file` to find the root cause and implement a fix. Runs tests before and after to verify.

**Tool scope:** `READ_ONLY_TOOLS + [edit_file, write_file, bash (test only), submit_patch]`

**LangGraph flow:**
```
analyze_error → locate_code → read_context → implement_fix → run_tests → submit
```

**Role prompt key sections:** identity, bug-fixing methodology, "verify before claiming fixed" rule, never guess root cause without reading the code

**Tests:** `tests/test_bug_fix_agent.py` — 5 tests (tool scoping, role prompt loads, handler callable)

**Checklist:**
- [ ] Write `backend/roles/bug_fix.md` (500+ word prompt)
- [ ] Write `backend/app/agents/bug_fix.py` with `BugFixAgent` class
- [ ] Define `BUG_FIX_TOOLS` list (read + edit + bash-test + submit_patch)
- [ ] Write 5 tests
- [ ] Commit: `feat: Bug Fix Agent`

---

### Phase 2B — Security Reviewer Agent
**File:** `backend/app/agents/security_reviewer.py`  
**Role:** `backend/roles/security_reviewer.md`

**What it does:** Audits code for OWASP Top 10 vulnerabilities: SQL injection, XSS, hardcoded secrets, insecure deserialization, broken auth, path traversal, command injection. Uses `secrets_scan`, `search_code`, `read_file`, `analyze_file`. Outputs structured findings with severity: critical/high/medium/low.

**Tool scope:** `READ_ONLY_TOOLS + [secrets_scan, submit_security_report]` — READ ONLY, no edits

**New submit tool:** `submit_security_report` — structured findings with severity levels

**Tests:** `tests/test_security_reviewer.py` — 6 tests

**Checklist:**
- [ ] Write `backend/roles/security_reviewer.md`
- [ ] Add `_SUBMIT_SECURITY_REPORT_TOOL` spec
- [ ] Write `backend/app/agents/security_reviewer.py`
- [ ] Define `SECURITY_REVIEWER_TOOLS`
- [ ] Write 6 tests
- [ ] Commit: `feat: Security Reviewer Agent`

---

### Phase 2C — Architecture Reviewer Agent
**File:** `backend/app/agents/architecture_reviewer.py`  
**Role:** `backend/roles/architecture_reviewer.md`

**What it does:** Reviews system design: layer separation, dependency direction, circular imports, God classes, missing abstractions, violation of SOLID principles. Uses `get_file_tree`, `import_graph`, `circular_dep_detect`, `list_classes`, `analyze_file`.

**Tool scope:** `READ_ONLY_TOOLS + [import_graph, circular_dep_detect, submit_review]`

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 4 tests
- [ ] Commit: `feat: Architecture Reviewer Agent`

---

### Phase 2D — SQL Agent
**File:** `backend/app/agents/sql_agent.py`  
**Role:** `backend/roles/sql_agent.md`

**What it does:** Handles all database tasks: write SQL queries, optimize slow queries (using EXPLAIN), design schema changes, review migrations, generate Alembic migration files. Uses `run_sql`, `explain_query`, `inspect_schema`, `run_migration`, `write_file`.

**Tool scope:** `READ_ONLY_TOOLS + [run_sql, explain_query, inspect_schema, write_file, submit_patch]`

**Tests:** 5 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 5 tests
- [ ] Commit: `feat: SQL Agent`

---

### Phase 2E — Docker Agent
**File:** `backend/app/agents/docker_agent.py`  
**Role:** `backend/roles/docker_agent.md`

**What it does:** Manages containerization: write Dockerfiles, docker-compose configs, build images, inspect running containers, read container logs, debug container failures. Uses `docker_build`, `docker_compose`, `docker_ps`, `docker_logs`, `docker_exec`, `write_file`.

**Tool scope:** `READ_ONLY_TOOLS + [docker_build, docker_compose, docker_ps, docker_logs, docker_exec, write_file, bash, submit_patch]`

**Tests:** 5 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 5 tests
- [ ] Commit: `feat: Docker Agent`

---

### Phase 2F — CI/CD Agent
**File:** `backend/app/agents/cicd_agent.py`  
**Role:** `backend/roles/cicd_agent.md`

**What it does:** Manages CI/CD pipelines — creates GitHub Actions workflows, analyzes build failures, suggests fixes for pipeline issues, monitors deployment status. Uses `read_file`, `write_file`, `fetch_url` (for CI API), `bash`, `create_pr`.

**Tool scope:** `READ_ONLY_TOOLS + [write_file, bash, create_pr, submit_patch]`

**Tests:** 4 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 4 tests
- [ ] Commit: `feat: CI/CD Agent`

---

### Phase 2G — Refactoring Agent
**File:** `backend/app/agents/refactor_agent.py`  
**Role:** `backend/roles/refactor_agent.md`

**What it does:** Improves code quality without changing behavior: extracts functions, renames symbols, removes duplication, simplifies complex conditions, organizes imports, applies consistent style. Uses `list_functions`, `list_classes`, `replace_function`, `rename_symbol`, `organize_imports`, `format_file`.

**Tool scope:** `CODER_TOOLS + [list_functions, list_classes, replace_function, replace_class, rename_symbol, organize_imports, format_file]`

**Tests:** 5 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 5 tests
- [ ] Commit: `feat: Refactoring Agent`

---

### Phase 2H — README Agent
**File:** `backend/app/agents/readme_agent.py`  
**Role:** `backend/roles/readme_agent.md`

**What it does:** Generates and updates README files. Reads project structure, imports, existing docs, and produces professional README with: purpose, setup, usage examples, API reference, architecture overview. Uses `get_file_tree`, `read_files`, `analyze_file`, `write_file`.

**Tool scope:** `READ_ONLY_TOOLS + [write_file, submit_docs]`

**Tests:** 4 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 4 tests
- [ ] Commit: `feat: README Agent`

---

### Phase 2I — API Docs Agent
**File:** `backend/app/agents/api_docs_agent.py`  
**Role:** `backend/roles/api_docs_agent.md`

**What it does:** Generates API documentation from FastAPI routes. Reads all `@router.*` decorated functions, their Pydantic schemas, and generates OpenAPI-style markdown documentation. Uses `find_route`, `find_api`, `read_file`, `analyze_file`, `write_file`.

**Tool scope:** `READ_ONLY_TOOLS + [find_route, find_api, write_file, submit_docs]`

**Tests:** 4 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 4 tests
- [ ] Commit: `feat: API Docs Agent`

---

### Phase 2J — Dependency Upgrade Agent
**File:** `backend/app/agents/dependency_agent.py`  
**Role:** `backend/roles/dependency_agent.md`

**What it does:** Audits and upgrades dependencies: reads requirements.txt/package.json, checks for outdated packages, checks for security vulnerabilities (`pip index versions`, `npm audit`), proposes updates with compatibility notes. Uses `read_file`, `bash`, `write_file`.

**Tool scope:** `READ_ONLY_TOOLS + [bash, write_file, submit_patch]`

**Bash allowlist (restricted):** `pip index versions *`, `pip show *`, `npm audit`, `npm outdated`, `pip install --dry-run`

**Tests:** 5 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 5 tests
- [ ] Commit: `feat: Dependency Upgrade Agent`

---

### Phase 2K — Monitoring Agent
**File:** `backend/app/agents/monitoring_agent.py`  
**Role:** `backend/roles/monitoring_agent.md`

**What it does:** Monitors system health: checks CPU/memory/disk, reads application logs, queries task queue depth, checks service health endpoints, alerts on anomalies. Uses `cpu_usage`, `memory_usage`, `disk_usage`, `health_check`, `task_progress`, `read_logs`.

**Tool scope:** `READ_ONLY_TOOLS + [cpu_usage, memory_usage, disk_usage, health_check, task_progress, read_logs, submit_health_report]`

**Tests:** 5 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 5 tests
- [ ] Commit: `feat: Monitoring Agent`

---

### Day 2 End Goal
- **New agents:** 11 (bug_fix, security_reviewer, architecture_reviewer, sql_agent, docker_agent, cicd_agent, refactor_agent, readme_agent, api_docs_agent, dependency_agent, monitoring_agent)
- **Total agents:** 26
- **Tests:** 530+ passing
- **mypy:** clean
- Commit: `day-2/agent-expansion`

---

## DAY 3 — Advanced Features + Browser + Memory + Polish

**Target:** Browser tools, memory layer, planning tools, documentation tools, remaining agents, MCP integrations.

---

### Phase 3A — Browser / Playwright Tools
**Requires:** `pip install playwright && playwright install chromium`  
**New tools:** `browser_open`, `browser_navigate`, `browser_screenshot`, `browser_read_dom`, `browser_click`, `browser_type`, `browser_close`

**Implementation notes:**
- Add `playwright` to `requirements.txt` (pin version)
- Create `backend/app/repo_tools/browser_driver.py` — singleton Playwright context manager
- All browser tools go through this driver to share one browser instance per session
- `browser_open(url)` — launch browser (headless), navigate to URL, return page title + status
- `browser_navigate(url)` — navigate current page
- `browser_screenshot(path=None)` — take screenshot, save to `/tmp/screenshot_<uuid>.png`, return path
- `browser_read_dom(selector=None)` — get page text content (or specific selector's innerText)
- `browser_click(selector)` — click element by CSS selector or text
- `browser_type(selector, text)` — type into input field
- `browser_close()` — close browser session
- Browser tools are NOT available to pipeline agents (READ_ONLY / CODER), only to chat_agent

**Tests:** `tests/test_browser_tools.py` — 10 tests (most use mocking since headless browser needs display)

**Checklist:**
- [ ] `pip install playwright` + `playwright install chromium` + pin version
- [ ] Create `backend/app/repo_tools/browser_driver.py`
- [ ] Add 7 tool specs to CHAT_TOOLS
- [ ] Add handlers in `make_chat_handlers()` and `_execute_tool()`
- [ ] Write 10 tests (mock-based for CI)
- [ ] Commit: `feat: Browser/Playwright tools — open, navigate, screenshot, read_dom, click, type`

---

### Phase 3B — Memory Tool Layer
**New tools:** `memory_read`, `memory_write`, `decision_log_append`, `task_history_query`, `known_issues_read`, `known_issues_write`  
**Storage:** `backend/app/memory/` directory (JSON files, per-session or per-project)

**Implementation notes:**
- `memory_read(key)` — read from `backend/memory/<repo_slug>.json` under the given key
- `memory_write(key, value)` — write to memory store (append-mode for lists, replace for strings)
- `decision_log_append(decision, reason, alternatives=None)` — appends to `backend/memory/<slug>_decisions.jsonl`
- `task_history_query(limit=20, status=None)` — query `task_logs` DB table via psql
- `known_issues_read()` — read `backend/memory/<slug>_known_issues.md`
- `known_issues_write(issue, severity)` — append issue to known issues file

**Tests:** 8 tests

**Checklist:**
- [ ] Create `backend/app/memory/` directory structure
- [ ] Add 6 tool specs
- [ ] Add handlers
- [ ] Write 8 tests
- [ ] Commit: `feat: Memory tool layer — read/write/decision_log/known_issues`

---

### Phase 3C — Planning + Documentation Tools (AI-powered)
**New tools:** `estimate_complexity`, `summarize_folder`, `generate_api_docs_text`, `mermaid_from_schema`

**Implementation notes:**
- `estimate_complexity(description)` — returns T-shirt size estimate (XS/S/M/L/XL) based on heuristics (token count of codebase sections, number of files likely affected). Purely heuristic, no LLM call from tool.
- `summarize_folder(path)` — read all .py/.ts files in folder (up to 20), return `analyze_file()` output for each → concat summary. The agent then synthesizes it.
- `generate_api_docs_text(route_path)` — parse FastAPI route file, extract all routes with types, return structured markdown template the agent fills in
- `mermaid_from_schema(table=None)` — run `inspect_schema` and convert output to a Mermaid ER diagram string

**Tests:** 8 tests

**Checklist:**
- [ ] Add 4 tool specs
- [ ] Add handlers
- [ ] Write 8 tests
- [ ] Commit: `feat: planning + docs generation tools`

---

### Phase 3D — Remaining Review Agents
**Files:** `performance_reviewer.py`, `style_reviewer.py`  
**Roles:** `backend/roles/performance_reviewer.md`, `backend/roles/style_reviewer.md`

**Performance Reviewer:**
- Reviews code for N+1 queries, missing indexes, unnecessary loops, blocking calls in async code
- Tools: `READ_ONLY_TOOLS + [run_sql (with EXPLAIN), find_sql, submit_review]`

**Style Reviewer:**
- Enforces code style: naming conventions, docstrings, line length, complexity, PEP 8 / Airbnb TS style
- Tools: `READ_ONLY_TOOLS + [run_linter, submit_review]`

**Tests:** 6 tests total

**Checklist:**
- [ ] Write 2 role prompts + 2 agent files
- [ ] Write 6 tests
- [ ] Commit: `feat: Performance Reviewer + Style Reviewer agents`

---

### Phase 3E — Sprint Planner + Business Analyst Agents
**Files:** `sprint_planner.py`, `business_analyst.py`  
**Roles:** `backend/roles/sprint_planner.md`, `backend/roles/business_analyst.md`

**Sprint Planner:**
- Takes epic/goal → breaks into sprint stories → estimates complexity → proposes execution order
- Tools: `READ_ONLY_TOOLS + [estimate_complexity, submit_result]`

**Business Analyst:**
- Analyzes business requirements → generates user stories → identifies edge cases → proposes acceptance criteria
- Tools: `READ_ONLY_TOOLS + [submit_result]`

**Tests:** 4 tests total

**Checklist:**
- [ ] Write 2 role prompts + 2 agent files
- [ ] Write 4 tests
- [ ] Commit: `feat: Sprint Planner + Business Analyst agents`

---

### Phase 3F — Migration Agent + Schema Agent
**Files:** `migration_agent.py`, `schema_agent.py`

**Migration Agent:**
- Analyzes ORM model changes, generates Alembic migration files, validates migrations are reversible
- Tools: `READ_ONLY_TOOLS + [run_sql, inspect_schema, run_migration, write_file, bash, submit_patch]`

**Schema Agent:**
- Designs database schemas, reviews existing schema for normalization issues, generates SQLAlchemy models from descriptions
- Tools: `READ_ONLY_TOOLS + [run_sql, inspect_schema, write_file, submit_patch]`

**Tests:** 5 tests total

**Checklist:**
- [ ] Write 2 role prompts + 2 agent files
- [ ] Write 5 tests
- [ ] Commit: `feat: Migration Agent + Schema Agent`

---

### Phase 3G — MCP / External Integrations (Tools only, no full agents)
**New tools:** `github_create_issue`, `github_list_prs`, `github_comment`, `linear_create_issue`, `slack_send_message`

**Implementation notes:**
- All MCP tools are thin wrappers around `gh` CLI (for GitHub) and curl-based API calls
- `github_create_issue(title, body, labels=[])` — `gh issue create ...`
- `github_list_prs(state="open")` — `gh pr list --state <state> --json number,title,state`
- `github_comment(issue_or_pr_number, body)` — `gh issue comment` or `gh pr comment`
- `linear_create_issue(title, description, team_key)` — requires `LINEAR_API_KEY` env var → curl to Linear API
- `slack_send_message(channel, text)` — requires `SLACK_WEBHOOK_URL` env var → curl webhook POST
- All external integration tools check for required env vars and return `[ERROR] <ENV_VAR> not set` if missing

**Tests:** 8 tests (all check graceful missing-config behavior)

**Checklist:**
- [ ] Add 5 MCP tool specs
- [ ] Add handlers with env var guards
- [ ] Write 8 tests
- [ ] Add `LINEAR_API_KEY`, `SLACK_WEBHOOK_URL` to `.env.example`
- [ ] Commit: `feat: MCP tools — GitHub, Linear, Slack integrations`

---

### Phase 3H — AI/ML Engineer Agent
**File:** `backend/app/agents/ai_engineer.py`  
**Role:** `backend/roles/ai_engineer.md`

**What it does:** Handles AI/ML tasks: prompt engineering, RAG pipeline setup, embedding generation, LLM evaluation, fine-tuning data preparation. Uses `read_file`, `write_file`, `run_python_snippet`, `bash`, `fetch_url` (for model APIs).

**Tool scope:** `CODER_TOOLS + [run_python_snippet, fetch_url]`

**Tests:** 4 tests

**Checklist:**
- [ ] Write role prompt + agent file
- [ ] 4 tests
- [ ] Commit: `feat: AI/ML Engineer Agent`

---

### Phase 3I — Cleanup Agent + Technical Debt Agent
**Files:** `cleanup_agent.py`, `tech_debt_agent.py`

**Cleanup Agent:**
- Removes dead code, unused imports, empty files, stale TODO comments, orphaned migration files
- Tools: `READ_ONLY_TOOLS + [dead_code_detect, find_todos, organize_imports, delete_file, edit_file, submit_patch]`

**Technical Debt Agent:**
- Identifies technical debt: long functions, high complexity, poor naming, missing tests, outdated patterns
- Tools: `READ_ONLY_TOOLS + [list_functions, find_todos, coverage_report, run_linter, submit_review]`

**Tests:** 5 tests

**Checklist:**
- [ ] Write 2 role prompts + 2 agent files
- [ ] 5 tests
- [ ] Commit: `feat: Cleanup Agent + Technical Debt Agent`

---

### Phase 3J — Final Integration Pass
**Goal:** Wire all new agents into the pipeline graph and the agent registry

**Tasks:**
- [ ] Register all new agents in `backend/app/agents/__init__.py`
- [ ] Add all new agents to the agent registry table via migration
- [ ] Update `backend/app/pipeline/graph.py` to include bug_fix and security_reviewer as optional nodes
- [ ] Update API routes if needed (`/api/agents` should return all 26 agents)
- [ ] Run full test suite: `pytest backend/tests/ -v --tb=short`
- [ ] Run mypy: `mypy backend/ --ignore-missing-imports`
- [ ] Run TypeScript check: `npx tsc --noEmit` in `apps/web/`
- [ ] Commit: `chore: final integration — all agents registered`

---

### Phase 3K — Final Polish & Documentation
**Tasks:**
- [ ] Write `docs/reports/COMPLETION_TEST_REPORT.md` with full test run output
- [ ] Update `PROJECT.md` with complete status
- [ ] Update `.env.example` with all new env vars (LINEAR_API_KEY, SLACK_WEBHOOK_URL, PLAYWRIGHT_HEADLESS)
- [ ] Verify `files/tools_agents.md` coverage — annotate each item with ✅ / ⚠️ / ❌
- [ ] Final commit: `docs: project completion — all tools and agents built`
- [ ] Tag release: `git tag v1.0.0-complete`

---

## Day 3 End Goal
- **New tools added:** ~22 more (browser + memory + planning + MCP)
- **Total CHAT_TOOLS:** ~131
- **New agents:** 10 more
- **Total agents:** 36
- **Tests:** 630+ passing
- **mypy:** clean on all files

---

## Complete Tool Coverage Tracker

### ✅ Already Built (69 tools)
`read_file` · `read_files` · `write_file` · `edit_file` · `append_file` · `rename_file` · `copy_file` · `delete_file` · `list_files` · `get_file_tree` · `find_file` · `file_exists` · `file_info` · `search_code` · `search_symbols` · `find_references` · `find_todos` · `search_imports` · `analyze_file` · `git_log` · `git_status` · `git_show` · `git_blame` · `git_diff` · `git_commit` · `git_branch` · `git_checkout` · `create_branch` · `git_stash` · `git_pull` · `git_fetch` · `git_restore` · `git_push` · `git_merge` · `git_reset` · `git_worktree` · `create_pr` · `generate_commit_msg` · `run_tests` · `run_linter` · `run_single_test` · `coverage_report` · `type_check` · `bash` · `run_background` · `kill_process` · `run_python_snippet` · `run_make` · `fetch_url` · `list_functions` · `list_classes` · `find_function_body` · `format_file` · `organize_imports` · `insert_at_line` · `replace_function` · `delete_lines` · `apply_patch` · `compare_files` · `read_logs` · `analyze_error` · `run_sql` · `inspect_schema` · `docker_ps` · `docker_logs` · `docker_exec` · `docker_compose` · `secrets_scan` · `submit_result`

### 📋 Day 1 Targets (planned)
`parse_ast` · `import_graph` · `call_graph` · `dead_code_detect` · `circular_dep_detect` · `rename_symbol` · `git_rebase` · `git_cherry_pick` · `read_output` · `run_node` · `run_script` · `docker_build` · `docker_restart` · `find_route` · `find_api` · `find_sql` · `find_test` · `find_config` · `cpu_usage` · `memory_usage` · `disk_usage` · `health_check` · `task_progress` · `replace_class` · `undo_changes` · `generate_patch` · `read_binary_file` · `explain_query` · `run_migration` · `seed_database`

### 📋 Day 3 Targets (planned)
`browser_open` · `browser_navigate` · `browser_screenshot` · `browser_read_dom` · `browser_click` · `browser_type` · `browser_close` · `memory_read` · `memory_write` · `decision_log_append` · `task_history_query` · `known_issues_read` · `known_issues_write` · `estimate_complexity` · `summarize_folder` · `generate_api_docs_text` · `mermaid_from_schema` · `github_create_issue` · `github_list_prs` · `github_comment` · `linear_create_issue` · `slack_send_message`

---

## Complete Agent Coverage Tracker

### ✅ Already Built (15)
`pm` · `architect` · `decomposer` · `planner` · `coder` · `backend_dev` · `frontend_dev` · `qa` · `reviewer` · `manager` · `devops` · `research` · `docs` · `executive` · `chat_agent`

### 📋 Day 2 Targets (11 new)
`bug_fix` · `security_reviewer` · `architecture_reviewer` · `sql_agent` · `docker_agent` · `cicd_agent` · `refactor_agent` · `readme_agent` · `api_docs_agent` · `dependency_agent` · `monitoring_agent`

### 📋 Day 3 Targets (10 new)
`performance_reviewer` · `style_reviewer` · `sprint_planner` · `business_analyst` · `migration_agent` · `schema_agent` · `ai_engineer` · `cleanup_agent` · `tech_debt_agent` + (optional: `prompt_engineer`, `rag_engineer`)

---

## Architecture Decisions Locked In

| Decision | Rationale |
|---|---|
| AST engine uses stdlib `ast` module | No extra dependencies, reliable for Python. Use grep for .ts/.tsx |
| Browser tools use Playwright (headless) | Most capable Python browser automation. `playwright install chromium` |
| Memory store = flat JSON files per repo slug | Simple, no extra infra. Upgrade to Redis later if needed |
| MCP tools = thin CLI/API wrappers | Fastest path. Real MCP protocol integration is a future phase |
| All new agents use same `base.py` pattern | Consistent: role prompt load + Anthropic SDK call + tool dispatch |
| Browser tools: chat_agent only | Too risky / slow for automated pipeline agents |
| run_migration always requires confirmation | Irreversible ops need human approval, no exceptions |

---

## Known Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Browser tools need a display in CI | Use headless mode + `PLAYWRIGHT_HEADLESS=1` env var; mock in tests |
| psql tools require DB to be running | Tests check for DB availability, skip gracefully if not connected |
| MCP tools require external API keys | Guard with env var checks, return `[ERROR] <KEY> not set` if missing |
| AST engine fails on syntax errors | Wrap in try/except, fall back to grep-based analysis |
| Memory file conflicts across sessions | Use file locking (`fcntl.flock`) for write operations |
| rename_symbol may have false positives | Show preview of matches before applying, require confirmation |

---

*Plan created: 2026-07-14*  
*Estimated completion: 3 focused sessions of 6-8 hours each*  
*Total new code: ~4000 lines Python · ~500 lines tests · ~300 lines role prompts*
