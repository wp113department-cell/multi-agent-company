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

## /repos REFERENCE RULE
- The `/repos` folder contains 10 cloned open-source projects (openhands, aider, continue, opencode, cline, roo-code, swe-agent, autogen, langgraph, composio). They are ARCHITECTURAL REFERENCES ONLY.
- You may READ them to understand patterns. You must NEVER copy, port, or paraphrase their source code into ours. All Gridiron code is original.

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
