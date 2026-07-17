# Fleet Enhancement Plan — 68 Agents, 20+ Capabilities
Last updated: 2026-07-17 | Status: Day 4 complete — 3 Platform Enhancements added for Day 5

---

## Reconciliation with Previous Plan (the artifact/PDF plan)

The original plan (artifact published earlier) covered Sessions S0–S20 with 65 agents.
This document supersedes it with the following updates:

| Old Plan | New Plan | Reason |
|---|---|---|
| 65 agents | 68 agents | 3 more discovered (groq_adapter, chat_agent, manager) |
| S0 = base_graph scaffold | Day 0 = enable flags + role prompts | S0 scaffold ALREADY BUILT in previous session |
| S1–S4 = migrate 13 old-style | Sessions 1–4 = ALREADY COMPLETE | Done in Sessions 1–4 |
| S5–S20 = AGENT_CONTRACT for 52 | Days 2–6 = AGENT_CONTRACT for 55 | Same work, updated agent count |
| No role prompt section | Day 8 = 9-section master template | Added from agent_enhancement.md requirements |
| No fleet agents section | Day 9 = 5 new fleet agents | Added from agent_enhancement.md §Fleet Agents |
| No budget/benchmark section | Days 10–11 = infra components | Added from agent_enhancement.md §§9,11 |
| Measurable objectives table | See section below (preserved exactly) | Critical — was missing from first draft |

**Old plan session groupings S5–S20 are preserved exactly in Days 2–6.** Same agents, same order, same contract tasks.

---

## Current State (as of Session 4)

| Group | Count | Status |
|---|---|---|
| 13 old-style agents | architect, decomposer, planner, backend_dev, frontend_dev, coder, reviewer, qa, devops, pm, research, executive, docs | ✅ Migrated to run_agent_graph + AGENT_CONTRACT |
| 55 base_graph agents | all others | On run_agent_graph but flags all False, no AGENT_CONTRACT |
| 5 fleet agents | performance_reviewer, agent_debugger, agent_advisor, knowledge_curator, quality_auditor | ❌ Not yet built |
| Infrastructure gaps | budget_manager, benchmark_manager, prompt_registry, regression_detector | ❌ Not yet built |

---

## The 20 Capabilities → What Code Delivers Each

| # | Capability | Code that delivers it | Status |
|---|---|---|---|
| 1 | Intelligent Understanding | planner_node (Haiku): {goal, hidden_intent, constraints, risks} | Built, flags=False |
| 2 | Deep Instruction Analysis | planner_node second call: {objectives, dependencies, missing_info, execution_plan} | Built, flags=False |
| 3 | Smart Planning | planner_node: gather-facts survey + create-plan (MagenticOne pattern) | Built, flags=False |
| 4 | Context Awareness | memory_hook_node: loads previous task summaries from memory/store.py | Built, flags=False |
| 5 | Long-Term Memory Usage | memory_hook_node: pgvector semantic search top-3 lessons injected | Built, flags=False |
| 6 | Learn From Success | lesson_node: Haiku extracts reusable pattern after submitted=True | Built, flags=False |
| 7 | Learn From Failure | retry router: Haiku generates failure insight on retry_count increment | Built, flags=False |
| 8 | Detect User Satisfaction | confidence field + stall counter → interrupt() for human review | Built, flags=False |
| 9 | Verification Before Reply | reflection_node: Sonnet call tool_choice=none after tool batch | Built, flags=False |
| 10 | Honest Error Handling | [ERROR] prefix in tool result → status=error → surfaced in AgentResult | ✅ Active |
| 11 | Credential Handling | policy/engine.py blocks .env writes; audit hook on credential-pattern tools | ✅ Active |
| 12 | Step-by-Step Guidance | planner_node output format for setup/debug tasks: numbered steps + checkpoints | Built, flags=False |
| 13 | Cross-Agent Collaboration | AGENT_CONTRACT dependencies[] + memory write category=fleet | Partial (13/68 have CONTRACT) |
| 14 | Shared Learning | lesson_node writes namespace=("fleet","lessons"); all agents query same ns | Built, flags=False |
| 15 | Architecture Awareness | memory_hook_node: context_builder.buildContext(repo_path) → state[repo_context] | Built, flags=False |
| 16 | Performance Awareness | run_span() wraps every run_agent_graph call (already active) | ✅ Active |
| 17 | Confidence Evaluation | state[confidence] set by planner_node; router checks vs CONFIDENCE_THRESHOLD | Built, flags=False |
| 18 | Self Review | reflection_node: {satisfied, issues} — if False re-enter tool loop | Built, flags=False |
| 19 | Continuous Improvement | lesson_node: extract lesson+pattern+optimization_ideas → memory/store.py | Built, flags=False |
| 20 | Production Quality | VerificationConfig + Tool manifest + Audit log + run_span = accumulated 1–19 | Partial |

**The core unlock: turn enable_planning=True, enable_memory=True, enable_reflection=True, enable_lesson=True per agent.**

---

## Additional Capabilities Beyond the 20 (Production-grade additions)

| # | Capability | Implementation |
|---|---|---|
| 21 | Structured output schemas | Pydantic model per agent result — validated before accepted |
| 22 | Per-agent timeout | max_turns cap + wall-clock timeout in run_agent_graph |
| 23 | Circuit breaker | After 3 consecutive failures → agent_registry status=DEGRADED, fleet_manager skips it |
| 24 | Rate limiting | Budget manager: max tokens/day per agent from config, not hardcoded |
| 25 | Health checks | agent_registry.heartbeat() every N minutes, publishes HealthUpdated event |
| 26 | Trace correlation | trace_id in every log line, bus event, audit entry, checkpoint (already scaffolded) |
| 27 | Role prompt versioning | Prompt registry: versioned .md files, proposal→review→approve→deploy lifecycle |
| 28 | Benchmark fixtures | Per-agent-type fixture repo; benchmark_manager.py runs + compares vs baseline |
| 29 | Regression detection | Compare current vs historical AgentResult; block promotion on decline |
| 30 | Cost budgeting | budget_manager.py: token_budget, cost_budget, concurrent_task_budget from config |

---

## Testing Strategy — Groq (now) vs Anthropic (later)

**While ANTHROPIC_API_KEY is unavailable, use the Groq shim for real-LLM tests.**

| Category | How to test | File |
|---|---|---|
| Unit (no LLM) | Mock anthropic.Anthropic — fast, always run | `tests/test_day0_capabilities.py` |
| Real LLM (Groq) | `groq_llm_patch` fixture — calls Groq API via shim | `tests/test_day0_groq_integration.py` |
| Real LLM (Anthropic-only) | `@anthropic_only` skip marker — run after key obtained | same file, bottom section |

**Run Groq tests:**
```bash
set -a && source .env && set +a   # loads GROQ_API_KEY + USE_GROQ=true
pytest tests/test_day0_groq_integration.py -v
```

**To remove Groq shim (once Anthropic key arrives):**
1. Set `ANTHROPIC_API_KEY=sk-ant-...` in `backend/.env`
2. Delete `tests/groq_compat.py`
3. Delete `tests/test_day0_groq_integration.py`
4. All other tests already mock the LLM — nothing else changes.

**For each new day's tests:** write one `test_dayN_groq_integration.py` with `[GROQ-OK]` tests using the `groq_llm_patch` fixture, plus `@anthropic_only` stubs for what Groq can't test. The stubs become real tests on Day 19 (cloud deploy with full Anthropic key).

---

## Session Rules (apply every day, no exceptions)

**Technical Debt Budget (§1):** Each session must allocate: 70% production improvements, 20% bug fixes, 10% refactoring. If a session is purely bug-fixing, reschedule the improvement work into the next session explicitly — never let a full session be only clean-up.

**Verified, not assumed:** After writing any code, run `python -c "import module"` + `mypy --strict` + relevant pytest subset. "It should work" is banned. Only "it ran and passed" counts.

**REPO-FIRST:** Before implementing anything non-trivial in a day: spend 5–10 minutes reading the relevant `/repos` reference. Extract the pattern. Then implement.

---

## Pre-Day 0 — Project Control Center + Repo Understanding

*These run BEFORE Day 0. They are one-time setup steps, not an agent build.*

### Pre-Day 0A: Create Feature Branch

```bash
git checkout -b fleet-enhancement-day0
```

Do NOT work on `main`. Every day ends with a commit on this branch. Merge to main only after Day 19 smoke test passes.

### Pre-Day 0B: Project Control Center

Create `docs/PROJECT_CONTROL_CENTER.md` — a single living document that answers at a glance:

```markdown
# Project Control Center — Live State
Last updated: YYYY-MM-DD

## Agent Production Readiness
| Agent | Flags | CONTRACT | Role Prompt (9-section) | VerificationConfig | Tests | Status |
|-------|-------|----------|------------------------|-------------------|-------|--------|
| architect | ✅ | ✅ | ✅ | ✅ | 12/12 | ✅ PRODUCTION |
| ... | | | | | | |

## Fleet OS Health
| Component | Status | Last Check |
|-----------|--------|------------|
| capability_registry | N agents registered | |
| agent_registry | N agents (Sleep: X, Running: Y, Degraded: Z) | |
| Event bus | 8 typed events, 0 ad-hoc | |
| Budget manager | active / not built | |
| Benchmark manager | active / not built | |
| Prompt registry | active / not built | |
| Regression detector | active / not built | |

## Open Issues
- [ ] issue description (day discovered)

## Completed Days
| Day | Date | Tests | Key deliverable |
|-----|------|-------|-----------------|
```

Update this file at the END of every day. It is the single source of truth — not PROJECT.md.

### Pre-Day 0C: Repo Understanding (10 Architecture Graphs)

Read the codebase top-to-bottom and produce `docs/ARCHITECTURE_GRAPHS.md` with these 10 maps (text-based, no external tools):

1. **Architecture Graph** — all service layers (API → pipeline → agents → DB → memory → bus)
2. **Agent Graph** — all 68 agents, which imports which, who calls who
3. **Tool Graph** — every tool used by every agent, grouped by permission level
4. **Workflow Graph** — pm → architect → decomposer → planner → coder → reviewer → qa → done
5. **Memory Flow** — how lessons enter memory, how they are retrieved, what shape they have
6. **DB Flow** — every ORM model, every FK relationship, every migration
7. **API Flow** — every FastAPI route, what it does, what it returns
8. **Dependency Graph** — requirements.txt grouped by purpose (LangGraph, Anthropic, DB, infra)
9. **Import Graph** — which modules import which (detect circular imports)
10. **Configuration Graph** — every env var in config.py, which agent/tool consumes it

These graphs are built by READING the code — no running it. Use `grep`, `ast.dump`, `import` tracing. They become the reference for every day's work so you never guess at "does this exist?"

---

## What Each Day Session Delivers

### Day 0 (Infrastructure — not counted in agent cadence)
**Goal:** Enable all 20 capabilities fleet-wide by upgrading base_graph.py feature flags

**Tasks:**
1. base_graph.py: set default flags enable_planning=True, enable_memory=True, enable_reflection=True, enable_lesson=True
2. base_graph.py: wire task_description, repo_path, model_haiku defaults from settings
3. role prompts: add 9-section master template to all 68 role files (Intelligent Understanding → Production Quality sections)
4. tests: 20 new tests proving each capability fires
5. **[Gap 7]** Agent Lifecycle Sleep wiring: after every `run_agent_graph()` call completes (success OR error), emit `HealthUpdated` event and transition `agent_registry` entry to `status=IDLE`. The Sleep state = "done and idle, available for next task." Wire this in `base_graph.py` post-graph hook.
6. **[Gap 10]** trace_id correlation: confirm `trace_id` flows from `AgentRunState` → every audit_log entry → every bus event payload → every checkpoint save. If any of these is missing the trace_id field, add it now. The goal: given a trace_id, you can reconstruct the full timeline of a run from bus events alone.

**Day 0 Exit Criteria (§20 — all 10 must pass before moving to Day 1):**
- [ ] `run_agent_graph()` default call fires planner_node → verify planner output in state
- [ ] `run_agent_graph()` default call fires memory_hook_node → verify state["memory_context"] populated
- [ ] `run_agent_graph()` default call fires reflection_node → verify state["verification"] populated
- [ ] `run_agent_graph()` default call fires lesson_node → verify memory write called
- [ ] All 68 role files exist and contain all 9 sections
- [ ] `fleet_checkpoint.py` saves a checkpoint → restores it → state is identical
- [ ] Agent registry entry transitions to IDLE after a completed run
- [ ] trace_id appears in: audit_log, bus event payload, checkpoint metadata
- [ ] `pytest backend/tests/ -q` → 0 failed (1525+)
- [ ] `mypy backend/ --strict` → 0 issues

**Success criteria:** All 10 exit criteria checked. run_agent_graph() with default kwargs activates all 4 nodes. 1525+ tests pass.

---

### Day 1 — 13 Migrated Agents: Enable Feature Flags
**Agents:** architect, decomposer, planner, backend_dev, frontend_dev, coder, reviewer, qa, devops, pm, research, executive, docs

**Tasks per agent:**
- Pass enable_planning=True, enable_memory=True, enable_reflection=True, enable_lesson=True
- Pass task_description=..., repo_path=settings.target_repo_path, model_haiku=settings.model_router
- Update VerificationConfig with real set_by fields (not empty)
- Update role prompt: add Intelligent Understanding + Self Review sections

**Success criteria:** All 13 agents call planner_node on every run. Tests pass.

---

### Day 2 — AGENT_CONTRACT for 55 base_graph agents (batch 1 of 5)
**Agents:** bug_fix, security_reviewer, architecture_reviewer, sql_agent, docker_agent, cicd_agent, refactor_agent, readme_agent, api_docs_agent, dependency_agent, monitoring_agent

**Tasks per agent:**
- Add AGENT_CONTRACT block (name, description, allowed_tools, input_types, output_types, side_effects, permissions, risk_level, expected_verification, dependencies)
- Add _register() at module level → capability_registry + agent_registry
- Confirm tool list in AGENT_CONTRACT matches actual tools used
- Confirm bash handlers use check_allowlisted_command
- Update role prompt: 9-section master template

**Success criteria:** All 11 in capability_registry. Fleet manager can select each by capability. Tests pass.

---

### Day 3 — AGENT_CONTRACT batch 2
**Agents:** performance_reviewer, style_reviewer, sprint_planner, business_analyst, migration_agent, schema_agent, ai_engineer, cleanup_agent, tech_debt_agent

Same task list as Day 2.

---

### Day 4 — AGENT_CONTRACT batch 3
**Agents:** release_notes_agent, evaluation_agent, rag_engineer_agent, changelog_agent, user_story_generator, security_architect, database_architect, manager

Same task list as Day 2.

---

---

## THREE PLATFORM ENHANCEMENTS (added 2026-07-17, land in Day 5)

These are cross-cutting platform features that affect all agents past and present.
Research source: `/home/pc-117/Documents/CRR2906/repos/` — opencode, roo-code, cline, langgraph, continue, open-hands, composio.

---

### Enhancement P1 — Streaming Agent Activity UI (Claude Code in the web)

**What it is:** Real-time agent activity feed in the Next.js web portal (port 3000) that shows users:
- What the agent is thinking (planner_node output, reflection output)
- Which files are being read / written / edited
- Which terminal commands are running and their output
- Token usage counter (live, in header and sidebar)
- A "Stop" button that pauses the agent mid-run, saves state, then opens a chat input so the user can inject new instructions, add files via `@` or `+`, and resume

**Reference repos used:**
- `opencode/packages/schema/src/session-event.ts` — typed event system: `Step.Started/Delta/Ended`, `Tool.Called/Progress/Success/Failed`, `Text.Started/Delta/Ended`, `Revert.Staged/Committed`
- `roo-code/src/core/task/Task.ts` — `abort: boolean` flag pattern; `abortReason: ClineApiReqCancelReason`; state saved before abort returns
- `continue/core/context/providers/FileContextProvider.ts` — `FileAttachment { uri, name, description, source }` → passed as fenced code blocks in context
- `opencode/packages/schema/src/prompt-input.ts` — `Prompt { text, files: FileAttachment[], agents: AgentAttachment[] }`
- `langgraph/libs/langgraph/langgraph/types.py` — `interrupt(value)` + `Command(resume=...)` for mid-run injection

**Architecture — Backend (`backend/app/`):**

```
app/
  services/
    activity_stream.py    ← NEW: singleton SSE event bus for per-task streaming
  api/
    activity.py           ← NEW: GET /api/tasks/{id}/stream  (SSE endpoint)
                                  POST /api/tasks/{id}/stop   (sets cancellation flag)
                                  POST /api/tasks/{id}/resume (injects message + files)
                                  GET  /api/tasks/{id}/token-usage
  pipeline/
    event_hooks.py        ← NEW: hook callbacks injected into base_graph.py
```

**Event stream format (SSE, `text/event-stream`):**
```json
{"type": "thinking",     "content": "Analyzing the task requirements...", "agent": "planner"}
{"type": "tool_call",    "tool": "read_file", "input": {"path": "backend/app/main.py"}, "id": "tc_1"}
{"type": "tool_result",  "tool": "read_file", "preview": "First 200 chars...", "id": "tc_1", "ok": true}
{"type": "file_edit",    "path": "backend/app/api/tasks.py", "action": "write", "lines_changed": 12}
{"type": "terminal",     "command": "pytest tests/ -q", "output": "37 passed", "exit_code": 0}
{"type": "token_usage",  "tokens_in": 1240, "tokens_out": 340, "cost_usd": 0.0043}
{"type": "agent_switch", "from": "planner", "to": "coder"}
{"type": "stopped",      "checkpoint_id": "ckpt_abc123", "tokens_in": 1240, "tokens_out": 340}
{"type": "done",         "result": {...}, "tokens_in": 3200, "tokens_out": 800, "cost_usd": 0.014}
{"type": "error",        "message": "Max retries exceeded", "recoverable": false}
```

**Stop + Resume flow:**
```
User clicks Stop
→ POST /api/tasks/{id}/stop
→ backend sets task._abort_flag = True in ActivityStream singleton
→ base_graph.py checks flag after each node, calls interrupt() if set
→ LangGraph saves checkpoint via fleet_checkpoint.py
→ returns {"stopped": true, "checkpoint_id": "ckpt_abc123"}
→ frontend opens chat input panel (same SSE connection, now bidirectional via POST)

User types message, optionally attaches files via @ or +
→ POST /api/tasks/{id}/resume  {"message": "...", "files": [{"uri": "...", "name": "...", "content": "..."}]}
→ backend loads checkpoint from fleet_checkpoint.py
→ injects message + file contents into LangGraph state via Command(resume={...})
→ SSE stream resumes from where it stopped
```

**File attachment format (@ and + button):**
```json
{
  "uri": "file:///home/user/project/auth.py",
  "name": "auth.py",
  "content": "full file content as string",
  "mime_type": "text/x-python"
}
```
Files sent: PDF (extract text via PyMuPDF), images (base64 encoded → vision message), `.md`/`.txt`/code files (raw content), Word/Excel (convert via python-docx/openpyxl).
File content is injected into the agent's system context as fenced code blocks (Continue pattern).

**Frontend changes (`apps/web/`):**
```
pages/tasks/[id]/stream.tsx   ← NEW: streaming activity feed page
components/
  ActivityFeed.tsx             ← NEW: renders typed events in real-time
  ThinkingBlock.tsx            ← NEW: collapsible thinking display
  FileEditBlock.tsx            ← NEW: shows file path + line count changed
  TerminalBlock.tsx            ← NEW: shows command + output with syntax color
  TokenCounter.tsx             ← NEW: live counter in header
  StopButton.tsx               ← NEW: stop → chat input panel
  FileAttachButton.tsx         ← NEW: + button → file picker (local or @repo)
  ChatInputPanel.tsx           ← NEW: appears after stop; accepts text + files
```

**Retroactive impact on Days 0–4:**
All 41 already-upgraded agents automatically benefit from the event stream because the stream hooks live in `base_graph.py` — no per-agent code change needed. The only per-agent enhancement is emitting `{"type": "thinking"}` from the planner_node output already stored in state.

---

### Enhancement P2 — Central Model Router (68-agent multi-provider LLM routing)

**What it is:** A single `ModelRouter` class in `backend/app/fleet/model_router.py` that:
- Maps all 68 agents to their designated model and provider (from `files/agent_models.md`)
- Returns `(provider, model, token_config)` for any agent name — no hardcoded model strings in agent files
- Supports Anthropic SDK (Claude Opus 4.1, Claude Sonnet 4) and OpenAI SDK (GPT-5.5) from one interface
- Smart token budgets: Opus agents get more tokens + thinking budget; Sonnet gets standard; GPT-5.5 configured for structured output

**Reference repos used:**
- `composio/python/providers/anthropic/composio_anthropic/provider.py` — `wrap_tool()` re-serializes unified Tool → Anthropic ToolParam
- `autogen/python/packages/autogen-core/src/autogen_core/models/_model_client.py` — `ChatCompletionClient` ABC + `ModelInfo` TypedDict; provider-agnostic interface
- `aider/aider/models.py` — LiteLLM `litellm_provider` string prefix; simplest possible routing via `anthropic/claude-...` or `openai/gpt-...`

**Architecture:**

```
backend/app/fleet/
  model_router.py          ← NEW: ModelRouter class + route(agent_name) → RouteConfig
  agent_models.json        ← NEW: the 68-agent mapping table (from files/agent_models.md)
  providers/
    base.py                ← NEW: LLMProvider ABC: call(messages, tools, config) → response
    anthropic_provider.py  ← NEW: wraps anthropic.Anthropic SDK
    openai_provider.py     ← NEW: wraps openai.OpenAI SDK (for GPT-5.5 agents)
```

**`agent_models.json` format (derived from `files/agent_models.md`):**
```json
{
  "architect":          {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "decomposer":         {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "planner":            {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "executive":          {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "research":           {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "manager":            {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "rag_engineer_agent": {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "security_architect": {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "backend_dev":        {"provider": "openai",    "model": "gpt-5.5",                "tier": "gpt"},
  "coder":              {"provider": "openai",    "model": "gpt-5.5",                "tier": "gpt"},
  "...":                {}
}
```

**Token config by tier:**
```python
TOKEN_CONFIGS = {
    "opus":   {"max_tokens": 8192,  "thinking_budget": 2048, "temperature": 1.0},
    "sonnet": {"max_tokens": 4096,  "thinking_budget": None,  "temperature": 1.0},
    "haiku":  {"max_tokens": 1024,  "thinking_budget": None,  "temperature": 0.5},
    "gpt":    {"max_tokens": 4096,  "thinking_budget": None,  "response_format": "json_object"},
}
```

**`ModelRouter` interface:**
```python
class ModelRouter:
    def route(self, agent_name: str) -> RouteConfig:
        """Return provider, model, token_config for agent_name."""
    
    def get_provider(self, agent_name: str) -> LLMProvider:
        """Return configured provider instance ready to call."""
    
    def token_budget(self, agent_name: str) -> dict[str, Any]:
        """Return token limits for agent_name."""
```

**`config.py` additions (no hardcoding):**
```
OPENAI_API_KEY=sk-...           # for GPT-5.5 agents
AGENT_MODELS_PATH=backend/app/fleet/agent_models.json  # can swap entire routing table
MODEL_OVERRIDE_architect=...   # per-agent override without code change
MAX_TOKENS_OPUS=8192
MAX_TOKENS_SONNET=4096
MAX_TOKENS_GPT=4096
THINKING_BUDGET_OPUS=2048
```

**`base_graph.py` integration:**
```python
# Replace: model=settings.model_coder in run_agent_graph()
# With:    model = model_router.route(role_name).model
#          provider = model_router.get_provider(role_name)
# The graph uses provider.call() instead of anthropic.messages.create() directly
# This makes ALL 68 agents use the correct model automatically once wired
```

**Retroactive impact on Days 0–4:**
All 41 already-upgraded agents are currently hardcoded to `settings.model_coder` or `settings.model_planner`. Day 5 wires them all to `model_router.route(role_name)` instead. This is a single-point change in `base_graph.py` — no per-agent changes needed after that.

---

### Enhancement P3 — Repo Console (Clone → Work → Push, no cloud needed)

**What it is:** A web console in the portal (port 3000) where users can:
1. Paste a GitHub/GitLab URL → backend clones it to a local path they choose
2. See the repo file tree, current branch, git status
3. All agent work runs inside that cloned repo path (uses existing `target_repo_path` in config)
4. Push changes, create branches, view diffs — all from the web UI
5. No Docker, no cloud — runs fully local on the user's machine

**Reference repos used:**
- `open-hands/openhands/app_server/utils/git.py` — `is_valid_git_branch_name()` + `ensure_valid_git_branch_name()` via subprocess; safe branch validation before git ops
- `roo-code/src/core/task/Task.ts` — workspace-bound agent: all file operations scoped to a single root path; no escape beyond that path
- `swe-agent/sweagent/environment/swe_env.py` — repo isolation concept: agent lives inside one repo dir, cannot touch parent

**Architecture:**

```
backend/app/
  services/
    git_service.py         ← NEW: subprocess git ops (clone, status, diff, add, commit, push, branch)
    workspace_service.py   ← NEW: manage active workspace path, validate scope, prevent path escape
  api/
    console.py             ← NEW: REST + SSE endpoints for repo console
```

**`git_service.py` — git operations (no shell injection):**
```python
class GitService:
    def clone(self, url: str, dest_path: str) -> AsyncGenerator[str, None]:
        """Stream clone progress via SSE. url validated against allowlist pattern."""
    
    def status(self, repo_path: str) -> GitStatus:
        """Return branch, staged, unstaged, untracked files."""
    
    def diff(self, repo_path: str, staged: bool = False) -> str:
        """Return git diff output."""
    
    def commit(self, repo_path: str, message: str, files: list[str]) -> str:
        """Stage specific files and commit. Never uses git add -A."""
    
    def push(self, repo_path: str, branch: str, force: bool = False) -> AsyncGenerator[str, None]:
        """Stream push progress. force=True requires explicit user confirmation."""
    
    def create_branch(self, repo_path: str, branch: str) -> None:
        """Create and checkout branch. Name validated via git check-ref-format."""
```

**Console API endpoints:**
```
POST /api/console/clone          {"url": "https://github.com/...", "dest": "/home/user/projects/myrepo"}
                                  → streams clone progress as SSE
GET  /api/console/status         → {branch, staged, unstaged, untracked, ahead, behind}
GET  /api/console/files          → file tree of active workspace (like file browser)
GET  /api/console/diff           → full git diff of workspace
POST /api/console/commit         {"message": "...", "files": [...]}
POST /api/console/push           {"branch": "...", "force": false}
POST /api/console/branch         {"name": "feature/xyz"}
GET  /api/console/log            → recent git log (last 20 commits)
POST /api/console/workspace      {"path": "/path/to/existing/repo"} → set active workspace
```

**Security rules (enforced in `workspace_service.py`):**
```python
# 1. All git operations scoped to WORKSPACE_ROOT (set once at session start)
# 2. dest_path for clone must be under ALLOWED_WORKSPACE_PARENT from config
# 3. URL allowlist: only https:// github.com, gitlab.com, bitbucket.org (configurable)
# 4. No git push --force to main/master without explicit confirmation
# 5. All shell calls use subprocess list form (no shell=True) — no injection possible
# 6. Path traversal check: os.path.realpath(path).startswith(WORKSPACE_ROOT)
```

**Frontend (`apps/web/`):**
```
pages/console/index.tsx     ← NEW: main console page
components/
  RepoClonePanel.tsx         ← NEW: URL input + path picker + stream clone progress
  FileBrowser.tsx            ← NEW: tree view of active repo
  GitStatusPanel.tsx         ← NEW: shows branch, staged/unstaged files, diff viewer
  CommitPanel.tsx            ← NEW: select files, write message, commit + push
  BranchPanel.tsx            ← NEW: create/switch branches
  ConsoleOutput.tsx          ← NEW: streaming git command output
```

**`.env.example` additions:**
```
ALLOWED_WORKSPACE_PARENT=/home/user/projects   # clones must land under this
GIT_ALLOWED_HOSTS=github.com,gitlab.com,bitbucket.org
```

**Retroactive impact on Days 0–4:**
None. The console uses the existing `target_repo_path` that all agents already accept. Once the user clones a repo via the console, they set it as the active workspace — agents then automatically use it via `settings.target_repo_path`.

---

## Retroactive Enhancement Checklist (Days 0–4 → must be updated in Day 5 BEFORE agent batch)

| Day | Agent/Component | Enhancement Required |
|-----|----------------|----------------------|
| Day 0 | `base_graph.py` | Add `on_event` callback param → called after each node with typed event dict. ActivityStream registers as the default handler |
| Day 0 | `base_graph.py` | Add `_abort_flag` check between every node. If set: call `interrupt()`, save checkpoint, return `{"stopped": true}` |
| Day 0 | `base_graph.py` | Replace `model=model_string` with `model=model_router.route(role_name).model` — reads from `agent_models.json` |
| Day 0 | `config.py` | Add: `OPENAI_API_KEY`, `AGENT_MODELS_PATH`, `MAX_TOKENS_OPUS/SONNET/GPT`, `THINKING_BUDGET_OPUS`, `ALLOWED_WORKSPACE_PARENT`, `GIT_ALLOWED_HOSTS` |
| Day 1–4 | All 41 agents | No per-agent code change — they inherit streaming from `base_graph.py` automatically |
| Day 1–4 | 8 Opus-tier agents | `model_router.route()` will return `claude-opus-4-20251101` for: architect, decomposer, planner, executive, research, manager, rag_engineer_agent, security_architect |
| Day 1–4 | GPT-5.5 agents | 29 agents will route to OpenAI; `openai_provider.py` must handle their tool schemas |
| All | `fleet_checkpoint.py` | Confirm `save()` is called before `interrupt()` fires — needed for Stop+Resume to work |

---

### Day 5 — AGENT_CONTRACT batch 4 + Three Platform Enhancements (UPDATED)

**This day now has two parts. Part A must complete before Part B.**

---

#### Day 5A — Platform Foundations (3 enhancements, must do first)

**Step 1 — Read repos (15 min, required before writing any code):**
- `opencode/packages/schema/src/session-event.ts` — exact event shape
- `roo-code/src/core/task/Task.ts` lines 264–280 — abort flag pattern
- `langgraph/libs/langgraph/langgraph/types.py` — `interrupt()` + `Interrupt` class
- `open-hands/openhands/app_server/utils/git.py` — subprocess git pattern
- `autogen/python/packages/autogen-core/src/autogen_core/models/_model_client.py` — `ChatCompletionClient` ABC

**Step 2 — Model Router (P2 first, enables P1 token tracking):**

File: `backend/app/fleet/model_router.py`
```python
# 1. Load agent_models.json at startup (from AGENT_MODELS_PATH config)
# 2. route(agent_name) → RouteConfig(provider, model, tier, token_config)
# 3. get_provider(agent_name) → LLMProvider instance (cached)
# 4. on unknown agent_name: log warning, fall back to settings.model_coder
# 5. ModelRouter is a singleton: get_model_router()
```

File: `backend/app/fleet/agent_models.json`
```json
{
  "architect":    {"provider": "anthropic", "model": "claude-opus-4-20251101",  "tier": "opus"},
  "decomposer":   {"provider": "anthropic", "model": "claude-opus-4-20251101",  "tier": "opus"},
  "planner":      {"provider": "anthropic", "model": "claude-opus-4-20251101",  "tier": "opus"},
  "executive":    {"provider": "anthropic", "model": "claude-opus-4-20251101",  "tier": "opus"},
  "research":     {"provider": "anthropic", "model": "claude-opus-4-20251101",  "tier": "opus"},
  "manager":      {"provider": "anthropic", "model": "claude-opus-4-20251101",  "tier": "opus"},
  "rag_engineer_agent": {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "security_architect": {"provider": "anthropic", "model": "claude-opus-4-20251101", "tier": "opus"},
  "reviewer":     {"provider": "anthropic", "model": "claude-sonnet-4-20251101","tier": "sonnet"},
  "qa":           {"provider": "openai",    "model": "gpt-5.5",                 "tier": "gpt"},
  "backend_dev":  {"provider": "openai",    "model": "gpt-5.5",                 "tier": "gpt"},
  "frontend_dev": {"provider": "openai",    "model": "gpt-5.5",                 "tier": "gpt"},
  "coder":        {"provider": "openai",    "model": "gpt-5.5",                 "tier": "gpt"},
  "...":{},
  "DEFAULT":      {"provider": "anthropic", "model": "claude-sonnet-4-20251101","tier": "sonnet"}
}
```
*(Full 68-agent mapping derived from `files/agent_models.md` — every agent listed there gets an entry.)*

File: `backend/app/fleet/providers/base.py`
```python
from abc import ABC, abstractmethod
class LLMProvider(ABC):
    @abstractmethod
    async def call(self, messages, tools, config) -> LLMResponse: ...
```

File: `backend/app/fleet/providers/anthropic_provider.py` — wraps existing `anthropic.Anthropic`
File: `backend/app/fleet/providers/openai_provider.py` — wraps `openai.OpenAI`

Wire into `base_graph.py`:
```python
# Inside run_agent_graph():
from app.fleet.model_router import get_model_router
route = get_model_router().route(role_name)
model = route.model   # replaces settings.model_coder
```

**Step 3 — Activity Stream Backend (P1 backend):**

File: `backend/app/services/activity_stream.py`
```python
# Singleton per task_id: stores asyncio.Queue
# push_event(task_id, event_dict) — called from base_graph hooks
# subscribe(task_id) → AsyncIterator[dict] — consumed by SSE endpoint
# set_abort(task_id) — sets cancellation flag checked by base_graph
# save_context(task_id, message, files) — stores resume payload
```

File: `backend/app/api/activity.py`
```python
# GET  /api/tasks/{id}/stream  → StreamingResponse(text/event-stream)
# POST /api/tasks/{id}/stop   → sets abort flag; returns checkpoint_id
# POST /api/tasks/{id}/resume → {"message": str, "files": list[FileAttachment]}
# GET  /api/tasks/{id}/token-usage → {"tokens_in": N, "tokens_out": N, "cost_usd": F}
```

`base_graph.py` hook additions:
```python
# After planner_node: push_event(task_id, {"type": "thinking", "content": plan_text, "agent": role_name})
# After each tool call: push_event(task_id, {"type": "tool_call", "tool": name, "input": inp})
# After each tool result: push_event(task_id, {"type": "tool_result", ...})
# After write_file: push_event(task_id, {"type": "file_edit", "path": path, "action": "write"})
# After bash: push_event(task_id, {"type": "terminal", "command": cmd, "output": out})
# Before each node: check abort flag → if set: interrupt() + push "stopped" event
# After graph ends: push_event(task_id, {"type": "done", "result": result, ...})
```

**Step 4 — Repo Console Backend (P3 backend):**

File: `backend/app/services/git_service.py` — async subprocess git wrapper
File: `backend/app/services/workspace_service.py` — path scope enforcement
File: `backend/app/api/console.py` — all console endpoints
Wire router into `backend/app/main.py`

**Step 5 — Frontend (P1 + P3 UI):**

Next.js pages and components listed in Enhancement P1 and P3 architecture above.
All use existing Tailwind + existing API client pattern.
SSE consumed via `EventSource` hook (`useEventSource`).
File attachment: `<input type="file">` for local files; `@` triggers a search-as-you-type dropdown over repo file tree.

**Step 6 — Tests for Day 5A:**

File: `backend/tests/test_model_router.py`
- `test_route_returns_correct_model_for_opus_agents` (architect, decomposer, etc.)
- `test_route_returns_openai_for_gpt_agents` (backend_dev, coder, etc.)
- `test_unknown_agent_falls_back_to_default`
- `test_token_config_by_tier`
- `test_agent_models_json_covers_all_68_agents`

File: `backend/tests/test_activity_stream.py`
- `test_push_and_subscribe_delivers_event`
- `test_abort_flag_set_prevents_new_events`
- `test_thinking_event_shape_valid`
- `test_tool_call_event_shape_valid`
- `test_done_event_has_result`

File: `backend/tests/test_git_service.py`
- `test_valid_url_passes`
- `test_disallowed_host_rejected`
- `test_path_traversal_rejected`
- `test_git_status_parses_output`
- `test_branch_name_validated`

**Day 5A Exit Criteria (all must pass before Day 5B):**
- [ ] `model_router.route("architect")` returns `claude-opus-4-20251101`
- [ ] `model_router.route("backend_dev")` returns `gpt-5.5` + `provider=openai`
- [ ] `agent_models.json` has entries for all 68 agents
- [ ] `GET /api/tasks/{id}/stream` returns `text/event-stream` with `data: {...}\n\n`
- [ ] `POST /api/tasks/{id}/stop` sets abort flag, stream emits `{"type": "stopped"}`
- [ ] `POST /api/console/clone` rejects non-allowlisted hosts
- [ ] `GET /api/console/status` returns branch + file counts
- [ ] All `test_model_router.py`, `test_activity_stream.py`, `test_git_service.py` tests pass
- [ ] Frontend renders at least one `thinking` event in the activity feed

---

#### Day 5B — AGENT_CONTRACT batch 4 (9 agents)

**Agents:** chat_agent, code_explainer_agent, code_quality_agent, accessibility_agent, api_designer_agent, compliance_agent, cost_estimator_agent, data_pipeline_agent, debugger_agent

**Same task list as Day 2** (AGENT_CONTRACT + _register() + fleet flags + VerificationConfig + role prompt)

**Additional for Day 5B agents:** each agent's model is now resolved via `model_router.route(role_name)` automatically — no manual `model=settings.model_coder` needed if Step 3 of Day 5A wired base_graph correctly.

**Day 5B Exit Criteria:**
- [ ] All 9 agents in capability_registry with non-empty capabilities
- [ ] All 9 agents have AGENT_CONTRACT + _register() + enforce_in_result non-empty
- [ ] Programmatic audit: 0 issues across all 50 agents (41 previous + 9 new)
- [ ] `test_day5_agent_contracts.py` + `test_day5_agents.py` pass
- [ ] Full suite: 1878+ tests pass (Day 5A tests + Day 5B tests added)

---

**Integration note for future days (Day 6 onward):** Every new agent and enhancement automatically benefits from P1 (streaming), P2 (correct model routing), and P3 (repo console) because:
- P1: hooks in `base_graph.py` fire for every `run_agent_graph()` call
- P2: `model_router.route(role_name)` is called once at graph entry; just add the agent to `agent_models.json`
- P3: uses `settings.target_repo_path` already passed to every agent

No per-agent work is needed to enable these 3 features on future agents.

---

### Day 6 — AGENT_CONTRACT batch 5
**Agents:** dependency_security_agent, devex_agent, env_checker_agent, feature_flag_agent, incident_responder_agent, infra_agent, load_test_agent, localization_agent, onboarding_agent, pair_programmer_agent, rollback_agent, runbook_generator_agent, slo_agent, spike_agent, test_coverage_agent, test_writer_agent, version_manager_agent, groq_adapter

Same task list as Day 2. Note: groq_adapter is not a task agent — verify it only needs registry entry, not AGENT_CONTRACT.

---

### Day 7 — VerificationConfig Hardening (all 68 agents)
**Goal:** Every agent has real set_by, enforce_in_result — no more empty VerificationConfigs

| Agent type | Required verification fields |
|---|---|
| Code writers (backend_dev, frontend_dev, coder, refactor_agent, cleanup_agent, migration_agent) | tests_passed via run_tests, diff_checked via git_diff |
| Reviewers (reviewer, security_reviewer, architecture_reviewer, code_quality_agent, style_reviewer) | review_submitted (read-only, no mutation) |
| QA agents (qa, test_writer_agent, test_coverage_agent, evaluation_agent) | tests_run via bash, coverage_measured |
| DB agents (sql_agent, schema_agent, database_architect, migration_agent) | schema_validated, migration_applied |
| Docs agents (docs, readme_agent, api_docs_agent, changelog_agent, runbook_generator_agent) | docs_written via write_file |
| Planning agents (pm, architect, decomposer, planner, sprint_planner, business_analyst) | brief_submitted |
| Security agents (security_reviewer, security_architect, dependency_security_agent) | vulnerabilities_checked |
| Infra agents (docker_agent, cicd_agent, infra_agent, devops) | checks_run via bash |
| Read-only agents (research, tech_debt_agent, cost_estimator_agent, slo_agent, env_checker_agent) | report_submitted |

**Success criteria:** verify_agent_contract() returns 0 violations for all 68 agents. Tests pass.

---

### Day 8 — Role Prompt Upgrades (all 68 role files)
**Goal:** Every role prompt has the 9-section master template

**9-section master template (add to every roles/*.md):**
```
## Understanding First
Before taking any action, identify: user goal, hidden intent, expected output, constraints, priorities, risks.

## Instruction Analysis
For complex/multi-part requests: split, identify objectives, dependencies, missing info, build execution plan, execute step-by-step.

## Smart Planning
Internally create: task list, execution order, dependency graph, validation steps, rollback plan. Then execute.

## Context Use
Use all available context: previous work, failures, project state, memory insights. Never ignore active context.

## Credential Safety
If credentials appear in input: route to config.py env var. Never hardcode. Never log. Confirm integration.

## Verification
Before every response verify: requirements covered, output correctness, tool results match, files changed, tests pass, edge cases handled.

## Honest Errors
If a mistake is detected: stop, verify, explain what happened and why, fix it, confirm the fix. Never hide or hallucinate success.

## Self Review
Before final output ask: Did I solve the real problem? Did I miss anything? Is this production ready? Can it break something?

## Production Quality
Every output must improve: maintainability, observability, robustness, modularity, testing. Never sacrifice simplicity.
```

**Success criteria:** All 68 role files contain all 9 sections. Existing tests still pass.

---

### Day 9 — Fleet-Level Enhancement Agents (5 new agents)
**Goal:** Build 5 new agents per agent_enhancement.md spec

**Agent 1: agent_performance_reviewer**
- Role: review other agents, detect weaknesses, repeated failures, suggest improvements, recommend prompt updates
- Tools: read_file, list_files, search_code, fleet_metrics_read, submit_review
- AGENT_CONTRACT: risk_level=low, read_repo + read_metrics

**Agent 2: agent_debugger**
- Role: detect failing agents, diagnose root cause, repair broken workflows, restore functionality, validate recovery, prevent recurrence
- Tools: read_file, search_code, bash (limited), audit_log_read, submit_fix
- AGENT_CONTRACT: risk_level=medium, write_repo (repair scope only)

**Agent 3: agent_advisor**
- Role: senior engineer of the fleet — review architecture, suggest better designs, reduce complexity, guide other agents
- Tools: read_file, list_files, search_code, get_file_tree, submit_advice
- AGENT_CONTRACT: risk_level=low, read-only

**Agent 4: knowledge_curator**
- Role: collect reusable knowledge, remove duplicates, improve memory quality, organize, share across agents
- Tools: read_file, memory_read, memory_write, memory_search, submit_curation
- AGENT_CONTRACT: risk_level=low, write_memory only

**Agent 5: quality_auditor**
- Role: audit prompts, tools, outputs, tests, contracts, safety, architecture, documentation. Generate improvement recommendations.
- Tools: read_file, list_files, search_code, get_file_tree, submit_audit
- AGENT_CONTRACT: risk_level=low, read-only

**Success criteria:** All 5 in capability_registry. Tests for each. Tests pass fleet-wide.

---

### Day 10 — Infrastructure: budget_manager + benchmark_manager + Tool Discovery
**Goal:** Three infrastructure components: §11 (budget), §9 (benchmark), §13 (tool discovery)

**[Gap 6] tool_discovery.py** (`backend/app/fleet/tool_discovery.py`):
```python
# Dynamic tool registry — replaces the static TOOL_MANIFEST dict
# At startup (or on-demand): scan every agent module for its AGENT_CONTRACT.allowed_tools
# Build a live index: capability_tag → [tool_name, ...] + tool_name → [agents_that_use_it]
#
# API exposed to agents:
#   discover_tools(capability: str) → list[ToolSpec]
#     "what tools are available for security-scanning tasks?"
#   check_compatibility(tool_name: str, agent_name: str) → bool
#     "can this agent use write_file given its risk_level?"
#   check_availability(tool_name: str) → bool
#     "is the bash handler for this tool actually registered?"
#   register_tool(spec: ToolSpec) → None
#     "plugin adds a new tool at runtime without restart"
#
# ToolSpec: name, description, permission_level, allowed_risk_levels, handler_path
# Discovery runs at import time via _register() hooks — no manual dict maintenance
```

**budget_manager.py** (`backend/app/fleet/budget_manager.py`):
```python
# Enforces per-agent limits from config (never hardcoded):
# MAX_TOKENS_PER_AGENT_RUN, COST_BUDGET_DAILY_USD, MAX_CONCURRENT_AGENTS
# Task exceeding budget → blocked, downgraded, deferred, or escalated per policy
# Integrates with run_span() to track spend
```

**benchmark_manager.py** (`backend/app/fleet/benchmark_manager.py`):
```python
# Maintains benchmark fixture repos per agent type
# Runs regression benchmarks: current result vs historical baseline
# Publishes performance trends
# Blocks promotion when regression thresholds exceeded
# 7 measurable objectives: latency_p50, tool_accuracy, hallucination_rate,
#   verification_coverage, compile_success, retry_success, benchmark_score
```

**Success criteria:** Tests for both. Budget enforcement tested with mock over-limit scenario. Tests pass.

---

### Day 11 — Infrastructure: Prompt Registry + Regression Detector + Versioned Memory
**Goal:** Three remaining infrastructure gaps from §10, §12, and §16

**prompt_registry.py** (`backend/app/fleet/prompt_registry.py`):
```python
# Versioned role prompts: each roles/*.md gets a version number in metadata
# Lifecycle: proposal → review → approved → deployed → rollback
# No prompt drift allowed — every change is a new version
# Rollback restores prior approved version
```

**regression_detector.py** (`backend/app/fleet/regression_detector.py`):
```python
# Compares current AgentResult against historical baseline per agent
# Detects decline in: correctness, latency, tool_accuracy, hallucination_rate, verification_coverage
# Blocks deployment when regression exceeds threshold (from config, not hardcoded)
# Tests passing alone is NOT sufficient — quality must also hold
```

**[Gap 4] versioned_memory.py** (`backend/app/fleet/versioned_memory.py`):
```python
# Versioned lesson lifecycle — prevents a weaker lesson from silently overwriting a stronger one
#
# States: DRAFT → PUBLISHED → SUPERSEDED → ARCHIVED
# Merge rule: when a new lesson is written for the same topic (detected by embedding similarity),
#   do NOT overwrite. Instead:
#   1. Create new version (V2) alongside existing (V1)
#   2. Run merge: Haiku call comparing V1 and V2 → produce V_merged (best of both)
#   3. Mark V1 as SUPERSEDED, V2 as MERGED_INTO, V_merged as PUBLISHED
#   4. ARCHIVED = manually retired or older than LESSON_RETENTION_DAYS from config
#
# Rollback: given a lesson_id, restore its previous PUBLISHED version
#   (useful when a new lesson turns out to be worse)
#
# lesson_node already calls memory_write — this module wraps that call with version logic
# All version metadata stored in the existing memory DB table (add version, state, supersedes_id columns)
```

**Success criteria:** Tests for all three. Version merge tested (write same topic twice → confirm merge). Regression block tested. Tests pass.

---

### Day 12 — End-to-End Pipeline Validation + Full System Wiring Verification
**Goal:** Prove the full pipeline runs a real task from input to output. Verify hierarchy chain, event compliance, and failure recovery ladder.

**Pattern source:** swe-agent `AbstractAgent.run()` — synchronous step loop, trajectory saved after every step, done on `submit` or max steps.

**Tasks — Part 1: Smoke Test**
1. Start backend: `uvicorn app.main:app --reload` — confirm startup, DB connection, all imports
2. POST a real task via API: `{"title": "Add hello world endpoint", "description": "Add GET /hello that returns {message: 'hello'}"}`
3. Trace the full pipeline: task created → pm_node → architect_node → decomposer_node → planner_node → coder_node → reviewer_node → qa_node → done
4. Log every node transition — which node runs, what it returns, how long it takes
5. Fix every failure found (broken imports, missing config, DB schema mismatch, agent not wired in pipeline/graph.py)
6. Repeat until one real task completes end-to-end

**Files to check:**
- `backend/app/pipeline/graph.py` — is the full pipeline wired?
- `backend/app/api/tasks.py` — does POST /tasks trigger the pipeline?
- `backend/app/db/session.py` — does the DB connection work?

**Tasks — Part 2: [Gap 5] Full Failure Recovery Ladder as code**

`fleet_checkpoint.py` already has Checkpoint + Rollback. Add the missing states:

```python
# Failure Recovery Ladder — all 7 states must be runnable code, not comments:
# Checkpoint  → save state at every node boundary (already exists in fleet_checkpoint.py)
# Rollback    → restore prior checkpoint and re-enter graph (already exists)
# Resume      → restore checkpoint and continue from where it stopped (no re-run from start)
# Retry       → increment retry_count, re-enter from SAME node with prior state intact
# Escalate    → set agent status=DEGRADED in agent_registry, notify fleet_manager
# Abort       → set task status=FAILED, preserve full checkpoint for human replay
# Human Review → emit ReviewRequested event, pause via interrupt(), await approval

# Wire these into base_graph.py error router:
# on error: retry up to MAX_RETRIES → escalate → abort → human_review
# on stall (confidence < threshold for N turns): escalate → human_review
```

**Tasks — Part 3: [Gap 8] Fleet OS Event Compliance Verification**

Write a static test in `backend/tests/test_event_compliance.py`:
```python
# Scan every agent module via AST + import
# Collect every `.emit(` call + every `event_type=` argument
# Assert the set of event types equals exactly:
#   {"TaskCreated", "TaskStarted", "TaskCompleted", "TaskFailed",
#    "ReviewRequested", "LessonPublished", "HealthUpdated", "MemoryCreated"}
# Any event type NOT in this set → test fails
# This test runs as part of the full suite on every day
```

**Tasks — Part 4: [Gap 11] Hierarchy Chain Verification**

Write an integration test in `backend/tests/test_hierarchy_chain.py`:
```python
# Verify the full chain is wired end-to-end:
# Executive → fleet_manager selects agent → capability_registry lookup → knowledge_graph context →
# agent_bus publishes TaskCreated → agent runs → tool_layer executes → verification_layer checks →
# reflection_node runs → lesson_node writes to learning_layer → AgentResult returned
#
# Test: POST a task (mocked LLM), trace that:
#   1. fleet_manager.select_agent() was called
#   2. capability_registry.get(agent_name) returned a spec
#   3. TaskCreated event emitted on bus
#   4. reflection_node received a non-empty verification dict
#   5. lesson_node called memory_write
#   6. AgentResult.result is non-empty
# If any step is missing: fail with "hierarchy chain broken at: X"
```

**Success criteria:** One real task (not mocked) runs from POST /tasks to final agent result. Pipeline logs show every node executing. All 7 failure recovery states are runnable code. Event compliance test passes (0 ad-hoc events). Hierarchy chain test passes (all 6 chain steps verified). 0 unhandled exceptions.

---

### Day 13 — Human Approval UI
**Goal:** Agent pauses, shows user what it wants to do, user approves/rejects, agent continues or stops.

**Pattern source:** LangGraph `interrupt()` + `Command(resume=...)` + `BaseCheckpointSaver` (langgraph/types.py line 811)

**Backend tasks (`backend/app/api/approvals.py`):**
```python
# 1. Agent calls interrupt(value) inside any LangGraph node
#    value = {"action": "push_to_github", "files": [...], "branch": "...", "details": "..."}
# 2. Graph freezes — state saved in checkpointer (AsyncPostgresSaver, already in DB)
# 3. Audit log records the pending approval

# New endpoints:
# GET  /api/approvals/pending          → list all pending interrupt() payloads
# GET  /api/approvals/{thread_id}      → get one approval request with full context
# POST /api/approvals/{thread_id}/approve  → sends Command(resume={"approved": True})
# POST /api/approvals/{thread_id}/reject   → sends Command(resume={"approved": False})
```

**LangGraph wiring:**
```python
# In any agent node that needs approval:
from langgraph.types import interrupt
decision = interrupt({
    "action": "push_code",
    "files_changed": files,
    "branch": branch_name,
    "diff_summary": diff[:500],
    "risk_level": "medium",
})
if not decision.get("approved"):
    return {**state, "stage": "rejected"}
# continue with push
```

**Frontend tasks (`apps/web/src/pages/approvals/`):**
- Approvals page: lists pending approvals with action type, files changed, risk level, diff preview
- Approve/Reject buttons that call the API
- Shows "Waiting for your approval" status on the task page
- Blocks pipeline visually until approved

**Success criteria:** Agent stops at approval gate. Frontend shows approval card. User clicks approve → pipeline resumes. User clicks reject → task marked rejected. Audit log has the approval decision. Tests for both API endpoints.

---

### Day 14 — Git Push Workflow
**Goal:** After task completes and user approves, create a branch, commit, create PR, notify user.

**Pattern source:** Open-Hands `GitHubPRsMixin.create_pr()` (open-hands/openhands/app_server/integrations/github/service/prs.py) + Aider `GitRepo.commit()` (aider/aider/repo.py line 131)

**New file: `backend/app/tools/git_push_tool.py`**
```python
# 1. Create workspace branch: openhands-workspace-{base62(os.urandom(16))}
# 2. Stage all changed files in worktree: git add -A
# 3. Generate commit message via Haiku: (task_title, diff) → one-line commit
# 4. Commit with attribution: GIT_COMMITTER_NAME="{user} (gridiron)" env var
# 5. Push branch to remote: git push origin {branch_name}
# 6. Create PR via GitHub REST API:
#    POST https://api.github.com/repos/{repo}/pulls
#    body: {title, head: branch, base: main, body: task_description, draft: True}
# 7. Return PR URL → stored in task record → shown in frontend
# Token: from credential vault (Day 17), never hardcoded, never logged
```

**Pipeline integration:**
```python
# In pipeline/graph.py: after qa_node passes
# → git_push_node (creates branch + commit)
# → approval_node (interrupt() with PR URL + diff summary)
# → if approved: push_to_remote_node (git push + create PR)
# → done
```

**New endpoints:**
```
GET  /api/tasks/{id}/pr          → PR URL and status
POST /api/tasks/{id}/push        → manually trigger push (for retry)
```

**Success criteria:** Task completion creates a real branch and PR on GitHub. PR URL stored in DB. Frontend shows PR link. Token never appears in logs. Tests for commit + PR creation (mock GitHub API).

---

### Day 15 — Blank Repo Bootstrap
**Goal:** Give an empty repo URL → agents scaffold the entire project structure, then begin implementation.

**Pattern source:** Open-Hands `clone_or_init_git_repo()` + `run_setup_scripts()` (app_conversation_service_base.py line 396 + 252) — 4-phase setup: PREPARING_REPOSITORY → RUNNING_SETUP_SCRIPT → SETTING_UP_GIT_HOOKS → LOADING_SKILLS

**New file: `backend/app/pipeline/bootstrap.py`**
```python
class RepoBootstrapper:
    """Detects blank repo and runs 4-phase initialization before main pipeline."""

    async def is_blank_repo(self, repo_path: str) -> bool:
        # Check: no commits, no src/, no pyproject.toml, no package.json
        result = subprocess.run(["git", "log", "--oneline", "-1"], cwd=repo_path, capture_output=True)
        return result.returncode != 0 or result.stdout.strip() == b""

    async def bootstrap(self, repo_path: str, project_type: str, task: str) -> BootstrapResult:
        # Phase 1: git init (if not already a repo)
        # Phase 2: run architect agent with "scaffold {project_type} project" instruction
        #          → produces file tree plan
        # Phase 3: run coder agent with scaffold plan → creates all files
        # Phase 4: commit initial scaffold as "chore: initial scaffold by gridiron"
        # Phase 5: continue with normal pipeline for the actual task
```

**Pipeline integration:** Before pm_node runs, check `is_blank_repo()`. If True → run bootstrap sequence first, emit `RepoBootstrapped` event, then continue to pm_node with the scaffolded repo.

**project_type detection:** Ask the user (via interrupt()) or detect from task description (Haiku call: "what type of project is this task describing: web-app / api / cli / library / data-pipeline?")

**Success criteria:** Given a blank dir, system detects it, asks user for project type (or detects from task), scaffolds structure, commits it, then runs the normal task. Test with an empty temp dir.

---

### Day 16 — Image Input Pipeline
**Goal:** User uploads image of website design → agents extract requirements → build it to match.

**Pattern source:** Cline `formatImagesIntoBlocks()` → `Anthropic.ImageBlockParam` (cline/apps/vscode/src/core/prompts/responses.ts line 351) + roo-code `resolveImageMentions()` with 5MB limit + 20MB total

**Backend tasks:**
```python
# New endpoint: POST /api/tasks/{id}/images
# Accepts: multipart/form-data with image files (png, jpg, jpeg, gif, webp)
# Validates: per-file 5MB limit, 20MB total, max 20 images
# Stores: base64 in task_images DB table (task_id, base64_data, mime_type, order)

# In pipeline: when task has images, inject into initial_message as Anthropic content blocks:
content = [
    {"type": "text", "text": f"Task: {task_description}\n\nReference images provided:"},
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<base64>"}},
    # ... more images
    {"type": "text", "text": "Build the UI to match these designs exactly."},
]
# Pass as messages[0]["content"] = content to run_agent_graph()
```

**New DB table (migration):**
```sql
CREATE TABLE task_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    base64_data TEXT NOT NULL,
    mime_type VARCHAR(50) NOT NULL,
    display_order INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Frontend tasks:**
- Image upload zone on the "New Task" form (drag-and-drop or click-to-upload)
- Preview thumbnails of uploaded images
- Images displayed on task detail page

**Which agents use images:** pm (understanding design intent), architect (component structure), frontend_dev (actual implementation), reviewer (visual comparison)

**Success criteria:** Upload a screenshot of a webpage. pm_node receives it as ImageBlockParam. architect produces component plan based on visual. frontend_dev builds matching HTML/CSS. Tests for upload endpoint + base64 encoding (no real LLM call needed).

---

### Day 17 — Credential Vault
**Goal:** User provides GitHub token, Anthropic key, DB URL etc. — stored securely, injected into agents, never logged.

**Pattern source:** Open-Hands `Secrets(BaseModel)` + `FileSecretsStore` + `SecretStr` + `expose_secrets` context gate (open-hands/openhands/app_server/secrets/)

**New file: `backend/app/security/credential_vault.py`**
```python
from pydantic import BaseModel, SecretStr

class ProjectCredentials(BaseModel):
    """Frozen — SecretStr fields never print in logs or repr."""
    model_config = {"frozen": True}

    github_token: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    database_url: SecretStr | None = None
    custom_secrets: dict[str, SecretStr] = {}

    def get_env_vars(self) -> dict[str, str]:
        """Call .get_secret_value() only here — the one safe extraction point."""
        env: dict[str, str] = {}
        if self.github_token:
            env["GITHUB_TOKEN"] = self.github_token.get_secret_value()
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key.get_secret_value()
        for k, v in self.custom_secrets.items():
            env[k] = v.get_secret_value()
        return env

class CredentialVault:
    """Per-project credential store. Backed by encrypted DB column or file."""
    async def store(self, project_id: str, creds: ProjectCredentials) -> None: ...
    async def load(self, project_id: str) -> ProjectCredentials: ...
    async def inject_into_env(self, project_id: str) -> dict[str, str]: ...
```

**Rules (enforced in code, not just prompt):**
- `SecretStr` fields: never serialized without `expose_secrets=True` context
- `get_env_vars()` is the only place `.get_secret_value()` is called
- Audit log records credential access (not the value, just the key name + timestamp)
- Policy engine blocks any agent tool call that writes to `.env*` files

**New endpoints:**
```
POST /api/projects/{id}/credentials   → store credentials (HTTPS only)
GET  /api/projects/{id}/credentials   → list key names only (never values)
DELETE /api/projects/{id}/credentials/{key}
```

**Success criteria:** Store a fake GitHub token. Load it. Inject into agent env. Confirm token never appears in any log line. Tests for SecretStr serialization guard. Tests for env injection. Policy engine test: agent cannot write token to .env file.

---

### Day 18 — Real-Time Streaming to Frontend (Pipeline Events)
**Goal:** User sees live updates as agents run — "pm_node thinking...", "architect planning...", "coder writing file X..."

**Pattern source:** OpenCode SSE with bounded asyncio.Queue (opencode/packages/server/src/handlers/event.ts) + FastAPI `StreamingResponse` + LangGraph `astream(stream_mode="messages")`

**Note:** Chat agent already has SSE streaming. This day wires the same SSE to the **pipeline** agents.

**Backend changes (`backend/app/api/tasks.py`):**
```python
# New endpoint: GET /api/tasks/{id}/stream
# Returns: text/event-stream
# Events emitted:
#   data: {"type": "node_start", "node": "pm_node", "timestamp": "..."}
#   data: {"type": "token", "node": "pm_node", "text": "Analyzing task..."}
#   data: {"type": "tool_call", "tool": "read_file", "input": {"path": "..."}}
#   data: {"type": "tool_result", "tool": "read_file", "success": true}
#   data: {"type": "node_done", "node": "pm_node", "duration_ms": 1234}
#   data: {"type": "approval_required", "thread_id": "...", "action": "..."}
#   data: {"type": "pipeline_done", "result": {...}}
#   : heartbeat (every 15s — prevents proxy timeout)

# Uses asyncio.Queue (capacity 256) per task_id
# LangGraph astream(stream_mode="messages") feeds tokens into the queue
# StreamingResponse reads from the queue
```

**Frontend changes (`apps/web/src/components/TaskStream.tsx`):**
- Live terminal-style output panel on task detail page
- Shows each agent phase as it starts/ends with timing
- Shows tool calls as they happen (file read/write, bash commands)
- Shows "Waiting for approval" when interrupt() fires
- Auto-scrolls, reconnects on disconnect (Last-Event-ID header)

**Success criteria:** Start a task. Frontend shows live node transitions within 500ms. Tool calls appear in real time. Approval gate shows as interactive card in the stream. Heartbeat tested with 16s wait. Tests for SSE encoder + queue behavior.

---

### Day 19 — Cloud Deployment (Vercel + Supabase)
**Goal:** Production URL. Anyone with API key can use the system.

**Note:** From memory — code is already ready, only infra needed.

**Tasks:**
1. Supabase project setup — run all migrations (001–007 + new ones from Days 12-18) against Supabase Postgres
2. Supabase pgvector extension enabled (`CREATE EXTENSION IF NOT EXISTS vector`)
3. Environment variables configured in Supabase + Vercel dashboards (no secrets in code)
4. `backend/` deployed as Python FastAPI on Railway or Render (Vercel doesn't run Python servers)
5. `apps/web/` deployed on Vercel — `NEXT_PUBLIC_API_URL` points to Railway/Render backend
6. GitHub Actions CI (`.github/workflows/ci.yml`) runs on every PR:
   - `pytest backend/tests/ -q` must pass
   - `mypy backend/ --strict` must pass
   - Deploy only on green main
7. Health check endpoint: `GET /health` returns `{"status": "ok", "db": "connected", "agents": N}`
8. Production smoke test: run one real task against the live deployment

**Success criteria:** Production URL accessible. Health check returns 200. One real task completes on production. CI blocks broken deploys. No secrets in any committed file.

---

## Complete Day-by-Day Reference

| Day | What | Type | Completion % |
|---|---|---|---|
| Day 0 | base_graph.py: enable all 4 flags + role prompt master template | Infra | ~68% |
| Day 1 | 13 migrated agents: enable_planning/memory/reflection/lesson flags | Enable flags | ~70% |
| Day 2 | bug_fix, security_reviewer, architecture_reviewer, sql_agent, docker_agent, cicd_agent, refactor_agent, readme_agent, api_docs_agent, dependency_agent, monitoring_agent | CONTRACT | ~72% |
| Day 3 | performance_reviewer, style_reviewer, sprint_planner, business_analyst, migration_agent, schema_agent, ai_engineer, cleanup_agent, tech_debt_agent | CONTRACT | ~74% |
| Day 4 | release_notes_agent, evaluation_agent, rag_engineer_agent, changelog_agent, user_story_generator, security_architect, database_architect, manager | CONTRACT | ~76% |
| Day 5 | chat_agent, code_explainer_agent, code_quality_agent, accessibility_agent, api_designer_agent, compliance_agent, cost_estimator_agent, data_pipeline_agent, debugger_agent | CONTRACT | ~77% |
| Day 6 | dependency_security_agent, devex_agent, env_checker_agent, feature_flag_agent, incident_responder_agent, infra_agent, load_test_agent, localization_agent, onboarding_agent, pair_programmer_agent, rollback_agent, runbook_generator_agent, slo_agent, spike_agent, test_coverage_agent, test_writer_agent, version_manager_agent, groq_adapter | CONTRACT | ~79% |
| Day 7 | All 68 agents — VerificationConfig hardening | All agents | ~80% |
| Day 8 | All 68 role files — 9-section master template | All roles | ~82% |
| Day 9 | agent_performance_reviewer, agent_debugger, agent_advisor, knowledge_curator, quality_auditor | New fleet agents | ~83% |
| Day 10 | budget_manager.py, benchmark_manager.py, tool_discovery.py | Infra | ~85% |
| Day 11 | prompt_registry.py, regression_detector.py, versioned_memory.py | Infra | ~87% |
| **Day 12** | **Smoke test + Failure Recovery Ladder + Event Compliance + Hierarchy Chain** | **Validation** | **~89%** |
| **Day 13** | **Human approval UI** — LangGraph interrupt() + FastAPI + frontend | **New feature** | **~91%** |
| **Day 14** | **Git push workflow** — branch + commit + GitHub PR + approval gate | **New feature** | **~93%** |
| **Day 15** | **Blank repo bootstrap** — detect empty repo + scaffold + 4-phase init | **New feature** | **~95%** |
| **Day 16** | **Image input pipeline** — upload + ImageBlockParam + vision task routing | **New feature** | **~96%** |
| **Day 17** | **Credential vault** — Pydantic SecretStr + FileSecretsStore + env injection | **New feature** | **~98%** |
| **Day 18** | **Real-time streaming** — wire pipeline agents to existing SSE + frontend terminal | **New feature** | **~99%** |
| **Day 19** | **Cloud deployment** — Supabase migrations + Railway/Render backend + Vercel frontend + CI | **Deploy** | **~100%** |

---

## Per-Agent Checklist (use every day)

```
Agent: _______________  Day: ___  Type: [ ] Enable-flags  [ ] CONTRACT  [ ] Prompt  [ ] New

CODE:
[ ] AGENT_CONTRACT block declared
[ ] run_agent_graph flags: enable_planning, enable_memory, enable_reflection, enable_lesson = True
[ ] task_description, repo_path, model_haiku passed
[ ] VerificationConfig: real set_by + enforce_in_result (not empty)
[ ] Tool list in AGENT_CONTRACT matches actual tools used
[ ] bash handlers use check_allowlisted_command
[ ] _register() at module level

FLEET OS:
[ ] capability_registry.py: agent registered with all capability tags
[ ] agent_registry.py: agent pre-registered (Sleep state)
[ ] Correct Fleet OS typed events emitted
[ ] audit_log.append() called for mutating actions
[ ] Fleet manager test: can select this agent by capability

ROLE PROMPT:
[ ] 9-section master template added to roles/<name>.md
[ ] Agent-specific instructions preserved
[ ] No hardcoded model names, thresholds, or URLs

TESTS:
[ ] Contract structure test
[ ] AST migration completeness check (no bare run_agent import)
[ ] Fleet manager selection test
[ ] Behavior test (mocked run_agent_graph)
[ ] Full suite: pytest backend/tests/ -q --tb=no → 0 failed
```

---

## Measurable Objectives — Report Template per Agent

Per Master Prompt §22: replace adjectives with numbers. If a metric cannot be computed yet, write `not yet measurable — needs X`. Never write "improved" without a number.

| Metric | Definition | How Measured | Where |
|---|---|---|---|
| latency_p50 | Median wall-clock time per run | Sort run times, take midpoint | fleet/metrics.py MetricsCollector.p50_latency_ms(agent) |
| latency_p95 | 95th percentile wall-clock time | Sort run times, 95th index | fleet/metrics.py MetricsCollector.p95_latency_ms(agent) |
| tool_accuracy | % of tool calls that succeeded | success_count / total_tool_calls | RunMetrics.tool_accuracy |
| hallucination_rate | % of claims not backed by verification key | VerificationConfig.enforce_in_result mismatches | base_graph.py enforce check |
| verification_coverage | % of submit fields wired through enforce_in_result | len(enforce_in_result) / len(submit fields) | Static check on VerificationConfig |
| compile_success | % of touched files that py_compile cleanly | py_compile after each edit | base_graph.py execute_tools node |
| retry_success | % of retries resolved before blocked | resolved_retries / total_retries | state["retry_count"] tracker |

**End-of-Day report format (required after every day):**

```
## Objective metrics (per agent enhanced today)
{agent}: latency_p50=..ms  tool_accuracy=..%  hallucination_rate=..%
         verification_coverage=..%  compile_success=..%  retry_success=..%
         benchmark_score=.. (fixture: ...)

## Fleet OS status
Capability Registry entries: N/68
Agent Bus event-type compliance: pass/fail
Tool Governance coverage: N tools manifested / M tools in use
Audit log: N approval decisions recorded today
Tests: N passed, 0 failed
```

---

## verify_agent_contract() — Required for Every Agent

After each agent is enhanced, run this check (already callable):
```python
from app.fleet.capability_registry import get_capability_registry
cap = get_capability_registry().get("agent_name")
assert cap is not None                          # registered
assert cap.risk_level in ("low", "medium", "high")
assert len(cap.capabilities) > 0               # at least one capability tag
assert len(cap.tools) > 0 or cap.risk_level == "low"
# For bash-using agents:
assert "bash" not in cap.tools or "execute_tests" in cap.tools  # must be scoped
```

0 violations required before marking an agent complete.

---

## Success Criteria (End State — Day 19 Complete)

**Agents:**
- 68 agents + 5 fleet agents = 73 total, all in capability_registry
- All 20 capabilities active on every agent (flags enabled, nodes running)
- All 30 capabilities (20 + 10 production additions) covered
- verify_agent_contract() returns 0 violations fleet-wide
- 7 measurable objectives computable per agent from real run data

**Infrastructure:**
- budget_manager blocks over-limit runs
- benchmark_manager detects regressions
- prompt_registry versions all role prompts
- regression_detector blocks promotions on quality decline

**Company workflow (the vision):**
- User gives any task → pm → architect → coder → reviewer → qa → done ✅
- User uploads image of design → agents build it to match ✅
- Empty repo given → bootstrap detects it → scaffolds project → runs task ✅
- Agent needs to push code → pauses → user sees PR diff → user approves → PR created ✅
- Credentials given securely → never logged → injected into agent environment ✅
- User sees live agent progress in real time (streaming terminal) ✅
- Everything runs on production URL (Vercel + Railway + Supabase) ✅

**Tests:**
- Full test suite: 1525+ passed → grows to 2000+ by Day 19
- 0 failed at every day boundary
- PROJECT.md updated after each day

**After Day 19: only test → debug → enhance loop remains. No more big builds.**

---

## Appendix A — Master Prompt for Daily Sessions

*Paste this at the start of every session. It tells Claude exactly what to do without you having to explain the plan again.*

```
You are working on the Gridiron Developer Department fleet enhancement project.

Read PROJECT.md now. Read docs/FLEET_ENHANCEMENT_PLAN.md now. Read docs/PROJECT_CONTROL_CENTER.md now.

Then:

1. Tell me what day we are on (Day 0 through Day 19) based on what is complete in PROJECT.md.
2. Tell me the current test count and whether it's green.
3. Execute TODAY'S day in full — all agents listed for this day, in order, one by one:

For each agent:
   a. Read the agent's current source file completely.
   b. Read the agent's current role file in roles/<name>.md.
   c. Apply ALL tasks from the plan for this day (enable flags / AGENT_CONTRACT / VerificationConfig / role prompt / etc.).
   d. Run the per-agent checklist from the plan — all boxes must be checked.
   e. Run: pytest backend/tests/ -q --tb=short → must be 0 failed before moving to next agent.
   f. Update docs/PROJECT_CONTROL_CENTER.md for this agent: mark its columns done.

4. After all agents for the day are done:
   - Run full suite: pytest backend/tests/ -v → 0 failed.
   - Run: mypy backend/ --strict → 0 issues.
   - Write docs/reports/DAY_<N>_REPORT.md with: agents enhanced, test counts, objective metrics, issues found.
   - Update PROJECT.md: what was built, files changed, test results, next day scope.
   - Git commit: "feat(fleet-os): Day N complete — <agents done>" with Co-Author trailer.

5. Print the end-of-day verdict:
   ✅ GREEN FLAG — DAY N COMPLETE: N tests pass, 0 failed, all agents enhanced.
   OR
   🔴 RED FLAG — DAY N BLOCKED: <exact issue>.

Rules for this session:
- NEVER skip a checklist item.
- NEVER claim success without running the test suite.
- NEVER hardcode anything — config.py only.
- NEVER invent a package — verify it exists first.
- When stuck: read /repos/<relevant-repo> first. Extract the pattern. Then implement.
- Technical debt budget: 70% improvements, 20% bug fixes, 10% refactoring.
```

---

## Appendix B — Gap Closure Summary

All 11 gaps identified in pre-Day-0 audit have been incorporated:

| Gap | Status | Where Added |
|-----|--------|-------------|
| Gap 1: Master Prompt for daily sessions | ✅ | Appendix A |
| Gap 2: Project Control Center | ✅ | Pre-Day 0B |
| Gap 3: Repo Understanding + 10 Graphs | ✅ | Pre-Day 0C |
| Gap 4: Versioned Memory (lesson V1→V2→Merged→Archived) | ✅ | Day 11 |
| Gap 5: Full Failure Recovery Ladder as code (Resume/Escalate/Abort) | ✅ | Day 12 Part 2 |
| Gap 6: Tool Discovery / Dynamic Registration (§13) | ✅ | Day 10 |
| Gap 7: Agent Lifecycle Sleep wiring | ✅ | Day 0 Task 5 |
| Gap 8: Fleet OS Event compliance verification (8 typed events only) | ✅ | Day 12 Part 3 |
| Gap 9: Technical Debt Budget (70/20/10) | ✅ | Session Rules header |
| Gap 10: Full trace_id correlation across all subsystems | ✅ | Day 0 Task 6 |
| Gap 11: §19 Hierarchy chain end-to-end verification | ✅ | Day 12 Part 4 |
