# CLAUDE.md — Permanent Project Rules (Gridiron Developer Department)

## SOURCE OF TRUTH
- The 20 spec documents (00–20 .md files) in this project are the source of truth. If your plan conflicts with them, the docs win.
- `project.md` is the LIVE STATE FILE. Read it at the START of every session. Update it at the END of every session. Never delete history from it — append.

## ZERO HALLUCINATION RULES (mandatory, every session)
1. NEVER invent an API, package, method, or config option. Before using ANY npm package: run `npm view <package> version` to confirm it exists and pin the real latest stable version in package.json.
2. Before using any Claude Agent SDK, LangGraph, Inngest, Supabase, or MCP API: read the actual installed package's TypeScript types in node_modules (or its README) and code against those types, not memory.
3. If you are unsure whether something exists, CHECK (read files, run commands) — never guess.
4. Every file path you reference must actually exist. Verify with ls/glob before importing.
5. After writing any code, you MUST run it (typecheck at minimum) before claiming it works. "It should work" is banned — only "it ran and passed" counts.

## ZERO HARDCODING RULES
1. No secrets, API keys, URLs, model names, thresholds, retry limits, or ports in source code. Everything goes through a single typed config module (`packages/shared-config`) that reads env vars and validates with Zod at boot. Missing required env = crash at startup with a clear message, never a silent default for secrets.
2. Model names live in config (e.g. MODEL_PLANNER, MODEL_CODER, MODEL_ROUTER) so we can swap models without code changes.
3. Policy rules, retry limits, concurrency caps: config or database tables, never inline constants.
4. Ship a complete `.env.example` with every variable documented.

## MODEL TIERING (cost control — mandatory)
- ROUTER/TRIAGE/HEARTBEAT/SUMMARY work → Claude Haiku (cheapest)
- CODING/QA/REVIEW agents → Claude Sonnet (best cost/quality for code)
- ARCHITECT/PM/MANAGER reasoning → Claude Sonnet (upgrade to Opus only via env var if quality demands it)
- Always enable prompt caching on system prompts and repeated context. Use the Context Cache (one context resolution per task, reused by all agents on that task).

## REAL AGENTS ONLY
- Every "agent" is a real Claude Agent SDK `query()` run with real tools, real MCP servers, and real scoped permissions — never a stub, never a mocked LLM response in production code paths (mocks allowed ONLY inside test files).

## /repos REFERENCE RULE
- The `/repos` folder contains 10 cloned open-source projects (openhands, aider, continue, opencode, cline, roo-code, swe-agent, autogen, langgraph, composio). They are ARCHITECTURAL REFERENCES ONLY.
- You may READ them to understand patterns. You must NEVER copy, port, or paraphrase their source code into ours. All Gridiron code is original. (See Gridiron Open Source Reference Matrix doc.)

## ENGINEERING STANDARDS (from doc 04)
- TypeScript strict mode everywhere, no implicit any. Zod schema for every agent output — validated before accepted.
- Monorepo: Turborepo. Structure: apps/web + packages/{task-engine, agent-runtime, repo-tools, policy-engine, event-bus, shared-types, shared-db, shared-config}.
- Conventional Commits. Every phase = its own git branch `stage-N/description`, merged only after tests pass.
- Simple > clever. Small files, pure functions, no dead code, no TODO-stubs left behind.

## PERMANENT SAFETY RULES (never relax, any phase)
- No agent writes to `.env*`, `secrets/**`, `.github/workflows/**` — enforced by PreToolUse hook in CODE, not prompt.
- No agent ever gets deploy credentials. Deploy is a human action forever.
- All agent code changes happen in isolated git worktrees until human approval.
- Max 3 self-correction retries → then status `blocked`, logs preserved.
- Every agent action logged to task_logs with timestamp + task_id + agent identity.

## END-OF-SESSION PROTOCOL (every prompt, no exceptions)
1. Run the FULL test suite (this phase + ALL previous phases' tests). All must pass.
2. Write `docs/reports/PHASE_<N>_TEST_REPORT.md` — what was tested, commands run, real output, pass/fail.
3. Update `project.md`: phase status, what was built, files created/changed, test results, known issues, exact next steps.
4. Git commit everything with a conventional commit message.
5. Print the final verdict: "✅ GREEN FLAG — PHASE N COMPLETE" only if every test passed, or "🔴 RED FLAG" with the exact remaining issues. Never print green flag with failing tests.