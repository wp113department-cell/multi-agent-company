# CLAUDE.md — Permanent Project Rules (Gridiron Developer Department)

## LANGUAGE ARCHITECTURE (PERMANENT — SET 2026-07-02)
- **Backend = Python ONLY.** FastAPI + LangGraph + Pydantic Settings + SQLAlchemy + Alembic.
- **Frontend = TypeScript ONLY.** Next.js in `apps/web/`. Calls Python FastAPI backend over HTTP.
- **TypeScript backend is archived in `TX/`.** Never port code from TX — read for reference only. All new backend is original Python.
- **Agent orchestration = LangGraph (Python).** Every multi-step agent flow is a LangGraph `StateGraph`.
- **No Node.js backend** — no Express, no Inngest, no ts-node in the backend path. Zero.

## SOURCE OF TRUTH
- The 20 spec documents (00–20 .md files) in this project are the source of truth. If your plan conflicts with them, the docs win.
- `PROJECT.md` is the LIVE STATE FILE. Read it at the START of every session. Update it at the END of every session. Never delete history from it — append.

## ZERO HALLUCINATION RULES (mandatory, every session)
1. NEVER invent a Python package, method, or API. Before using ANY pip package: run `pip index versions <package>` or `pip install <package>==999` to confirm it exists; pin the real latest stable version in `backend/requirements.txt`.
2. Before using any LangGraph, FastAPI, SQLAlchemy, Alembic, or Anthropic Python SDK API: read the installed package's source or docs in the venv and code against REAL APIs — not memory.
3. If you are unsure whether something exists, CHECK (read files, run commands) — never guess.
4. Every file path you reference must actually exist. Verify with ls/glob before importing.
5. After writing any code, you MUST run it (mypy typecheck + `python -c "import module"` at minimum) before claiming it works. "It should work" is banned — only "it ran and passed" counts.

## ZERO HARDCODING RULES
1. No secrets, API keys, URLs, model names, thresholds, retry limits, or ports in source code. Everything goes through `backend/app/config.py` — a Pydantic `BaseSettings` class that reads env vars. Missing required env = startup crash with a clear message, never a silent default for secrets.
2. Model names live in config (`MODEL_PLANNER`, `MODEL_CODER`, `MODEL_ROUTER`) so we can swap models without code changes.
3. Policy rules, retry limits, concurrency caps: config or database tables, never inline constants.
4. Ship a complete `.env.example` with every variable documented.

## MODEL TIERING (cost control — mandatory)
- ROUTER/TRIAGE/HEARTBEAT/SUMMARY work → Claude Haiku (cheapest)
- CODING/QA/REVIEW agents → Claude Sonnet (best cost/quality for code)
- ARCHITECT/PM/MANAGER reasoning → Claude Sonnet (upgrade to Opus only via env var if quality demands it)
- Always enable prompt caching on system prompts and repeated context.

## REAL AGENTS ONLY
- Every "agent" is a real LangGraph node calling the Anthropic Python SDK — never a stub, never a mocked LLM response in production code paths (mocks allowed ONLY inside test files).
- Every agent has: a real system prompt loaded from `backend/roles/<name>.md`, Zod-equivalent Pydantic output schema, real tools, and logs every action.

## REPO-FIRST RULE (PERMANENT — SET 2026-07-16)
**Before implementing ANY big or new feature:** Read the 10 reference repos first. Understand how they solve the same problem. Extract the pattern. Build a plan from what you found. THEN execute the plan in small tasks one by one. No exceptions.

**Process for every significant new capability:**
1. SEARCH `/repos` — find how existing open-source projects solved this problem
2. READ the relevant files — understand the real mechanism, not just the name
3. EXTRACT the pattern — what is the core idea, stripped of their framework?
4. PLAN — write a step-by-step implementation plan using that idea, adapted to our Python/LangGraph/FastAPI stack
5. EXECUTE — implement one small task at a time, test after each step
6. Never skip step 1–4. "I know how to do this" is not a substitute for checking.

## /repos REFERENCE RULE — ALL 10 REPOS WITH PATTERNS
The `/repos` folder contains 10 cloned open-source projects. They are ARCHITECTURAL REFERENCES ONLY.
You may READ them to understand patterns. You must NEVER copy, port, or paraphrase their source code. All Gridiron code is original.

### What each repo teaches us — look here first by problem type

| Repo | Path | Key Problem it Solves | What to Read |
|---|---|---|---|
| **aider** | `repos/aider/` | Repo-map generation, token-budget edit formats (diff/whole/udiff), auto-linting after edits, file watching | `aider/repomap.py` (symbol graph), `aider/coders/` (edit formats), `aider/linter.py`, `aider/repo.py` |
| **autogen** | `repos/autogen/` | Multi-agent orchestration, MagenticOne task ledger (gather-facts → create-plan → stall detection), MemoryController (pre-inference hook + failure insight), agent runtime, cancellation tokens | `python/packages/autogen-core/src/autogen_core/_base_agent.py`, `autogen-magentic-one/`, `_cache_store.py` |
| **cline** | `repos/cline/` | VS Code extension agent loop, tool approval flow, diff presentation, streaming to IDE, context window management | `apps/vscode/`, `sdk/` |
| **composio** | `repos/composio/` | Universal tool integration across LLM providers (Anthropic, OpenAI, LangGraph, AutoGen, CrewAI), tool schema normalization | `python/providers/` (anthropic/, langgraph/, autogen/), `python/composio/` |
| **continue** | `repos/continue/` | IDE context retrieval, context providers, autocomplete, MCP context, diff workflow | `core/context/providers/`, `core/context/retrieval/`, `core/autocomplete/`, `core/diff/` |
| **langgraph** | `repos/langgraph/` | StateGraph checkpointing (save/restore), persistent memory store (cross-thread), RetryPolicy, Send() fan-out, interrupt() for human-in-loop, RemainingSteps budget | `libs/checkpoint/`, `libs/langgraph/`, `libs/prebuilt/`, `libs/sdk-py/` |
| **opencode** | `repos/opencode/` | TUI coding agent, streaming output, tool execution in terminal, session/context management | `packages/core/`, `packages/app/`, `packages/cli/` |
| **open-hands** | `repos/open-hands/` | Docker sandbox isolation, repo.md always-on context injection, progressive interview before planning, human confirmation before memory write, full stack agent (browser + terminal + editor) | `openhands/agenthub/`, `openhands/runtime/`, `openhands/memory/`, `openhands/controller/` |
| **roo-code** | `repos/roo-code/` | VS Code agent checkpoint/rollback, auto-approval flow, context window condensation, context tracking, diff presentation | `src/core/checkpoints/`, `src/core/auto-approval/`, `src/core/condense/`, `src/core/context-management/` |
| **swe-agent** | `repos/swe-agent/` | SWE-bench environment isolation, history processors (compressing agent trajectory), action sampler, reviewer agent (second LLM reviews agent output), problem statement templating | `sweagent/agent/history_processors.py`, `sweagent/agent/reviewer.py`, `sweagent/environment/swe_env.py` |

### Problem → Repo lookup (use this to know WHERE to look)
| If you need to implement... | Check this repo first |
|---|---|
| Repo context injection, symbol map, file tree for agents | **aider** (`repomap.py`) |
| Multi-agent task planning, stall detection, fact-gathering | **autogen** (MagenticOne) |
| Memory update before inference, lesson extraction on failure | **autogen** (MemoryController) |
| StateGraph checkpoint → save → restore → rollback | **langgraph** (`libs/checkpoint/`) |
| Cross-thread persistent memory, shared lessons across agents | **langgraph** (`libs/checkpoint/store/`) |
| Tool integration for multiple LLM providers | **composio** (`python/providers/`) |
| Context compression / condense when context window fills | **roo-code** (`src/core/condense/`) |
| Auto-approval / human-in-loop flow | **roo-code** (`src/core/auto-approval/`) or **langgraph** (`interrupt()`) |
| History compression for long agent trajectories | **swe-agent** (`history_processors.py`) |
| Second-LLM review of agent output (reflect_on_tool_use) | **swe-agent** (`reviewer.py`) or **autogen** |
| Sandbox / Docker isolation for code execution | **open-hands** (`runtime/`) |
| Always-on repo context as system prompt prefix | **open-hands** (`agenthub/`) |
| Streaming output from agents to frontend | **opencode** (`packages/app/`) or **cline** |
| MCP context providers, retrieval pipeline | **continue** (`core/context/`) |
| Diff format selection, edit format comparison | **aider** (`coders/`) |

## PYTHON PROJECT STRUCTURE
```
backend/                   ← Python FastAPI + LangGraph backend
  app/
    config.py              ← Pydantic BaseSettings (env vars)
    main.py                ← FastAPI app, router registration
    db/
      models.py            ← SQLAlchemy ORM models
      session.py           ← async engine + session factory
    api/
      tasks.py             ← /api/tasks routes
      agents.py            ← /api/agents routes
      repo.py              ← /api/repo routes
    agents/
      base.py              ← shared agent runner (Anthropic SDK)
      pm.py                ← PM Agent (LangGraph node)
      architect.py         ← Architect Agent (LangGraph node)
      decomposer.py        ← Decomposer Agent (LangGraph node)
      planner.py           ← Planner Agent
      coder.py             ← Coder Agent
    pipeline/
      graph.py             ← LangGraph StateGraph definition
      state.py             ← Typed state schemas (Pydantic)
    policy/
      engine.py            ← Policy check functions
    repo_tools/
      scanner.py           ← AST + call graph
      embeddings.py        ← Voyage AI embedding pipeline
      context_builder.py   ← buildContext()
    mcp/
      server.py            ← MCP stdio server
  roles/                   ← Agent system prompts (markdown)
  migrations/              ← Alembic migration files
  tests/                   ← pytest tests
  requirements.txt         ← pinned deps
  requirements-dev.txt     ← dev/test deps
apps/web/                  ← Next.js frontend (TypeScript, unchanged)
TX/                        ← Archived TypeScript backend (reference only)
```

## ENGINEERING STANDARDS
- Python 3.11+. Strict type hints everywhere (`mypy --strict`). Pydantic v2 for all I/O schemas — validated before accepted.
- `ruff` for linting, `black` for formatting, `pytest` for tests.
- Conventional Commits. Every phase = its own git branch `stage-N/description`, merged only after tests pass.
- Simple > clever. Small modules, pure functions, no dead code, no TODO-stubs left behind.

## PERMANENT SAFETY RULES (never relax, any phase)
- No agent writes to `.env*`, `secrets/**`, `.github/workflows/**` — enforced in policy engine Python code, not prompt.
- No agent ever gets deploy credentials. Deploy is a human action forever.
- All agent code changes happen in isolated git worktrees until human approval.
- Max 3 self-correction retries → then status `blocked`, logs preserved.
- Every agent action logged to `task_logs` with timestamp + task_id + agent identity.

## END-OF-SESSION PROTOCOL (every prompt, no exceptions)
1. Run the FULL test suite (`pytest backend/tests/ -v` + `mypy backend/ --strict`). All must pass.
2. Write `docs/reports/PHASE_<N>_TEST_REPORT.md` — what was tested, commands run, real output, pass/fail.
3. Update `PROJECT.md`: phase status, what was built, files created/changed, test results, known issues, exact next steps.
4. Git commit everything with a conventional commit message.
5. Print the final verdict: "✅ GREEN FLAG — PHASE N COMPLETE" only if every test passed, or "🔴 RED FLAG" with the exact remaining issues. Never print green flag with failing tests.
