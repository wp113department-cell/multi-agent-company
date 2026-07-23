# MASTER AGENT AUDIT — All ~72 Agents

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.
# Run 01_MASTER_ARCHITECTURE_AUDIT.md first if you haven't — this audit
# assumes you already understand the two-graph structure and Fleet OS.
# Follow 00b_AUDIT_STANDARDS.md's evidence schema and JSON output for every
# finding in this audit.

You are a committee of Principal AI Architect + Principal Prompt Engineer +
Principal Multi-Agent Systems Engineer. Your job: audit EVERY agent in
`backend/app/agents/` individually against this project's own established
contract, not a generic ideal. Evidence-only. No assumptions. Say NOT FOUND
if something isn't in the code.

## PHASE 0 — Establish ground truth

1. Read `backend/app/fleet/capability_registry.py` fully — this is the
   authoritative list of registered agents and their capability tags.
2. Read `backend/app/fleet/tool_manifest.py` and
   `backend/app/agents/base_graph.py`'s `verify_agent_contract()` (or
   wherever it now lives) — this is the REAL enforcement logic, not the
   illustrative pseudocode in old planning docs. Use this function's actual
   rules as your pass/fail bar, not your own assumptions about what a
   contract should look like.
3. Read 3-4 representative role files under `backend/roles/`, including
   `_GLOBAL_STANDARDS.md`, to understand the 11-section constitution + 7
   role-specific sections (Non-Responsibilities, Success Criteria, Failure
   Conditions, Output Contract, Quality Gates, Edge Cases, Escalation) every
   role file is supposed to inherit/contain per PROJECT.md's Day 8 report.
4. Get the full agent list: `ls backend/app/agents/*.py` and
   `ls backend/roles/*.md`. Reconcile counts — PROJECT.md claims ~72
   registered capabilities / 67 role files (some agents like `executive` and
   `manager` legitimately have no VerificationConfig). Confirm actual counts
   match, and explain any discrepancy with evidence.

## PHASE 1 — Per-Agent Audit (do this for every agent file, not a sample)

For each agent in `backend/app/agents/*.py`, verify and score:

- [ ] Has `AGENT_CONTRACT` with real `input_types`/`output_types` (not stub)
- [ ] Has `VerificationConfig` with non-empty `enforce_in_result` — UNLESS
      it's `executive` (no tools, pure LLM) or `manager` (pure orchestrator,
      never calls run_agent_graph itself) — verify these two exceptions are
      still legitimate and no other agent silently lacks a config
- [ ] `enforce_in_result` keys are actually set by some tool in `set_by` —
      flag any dead/unreachable enforcement key
- [ ] Capability tag(s) are globally unique across the entire registry
      (cross-check against every other agent — PROJECT.md documents 2 real
      collisions found and fixed: business_analyst/user_story_generator,
      changelog_agent/release_notes_agent — confirm no regression, and scan
      for any NEW collision)
- [ ] `_register()` exists and is actually called at import time
- [ ] Role file exists at the exact path the agent loads
      (`backend/roles/{name}.md`) and is non-trivial (not a placeholder)
- [ ] Role file contains the 7 role-specific sections, not just inherited
      global standards
- [ ] Tool scope matches responsibility: read-only agents (reviewer,
      security_reviewer, architecture_reviewer, monitoring_agent, and the
      ~20+ "read-only auditor" agents) must NOT have write_file/edit_file/
      bash-with-write access — verify by reading the actual tool list
      constant each agent imports, not the role file's prose
- [ ] Coder-class agents (coder, backend_dev, frontend_dev, bug_fix,
      refactor_agent, sql_agent, migration_agent, cleanup_agent) have
      self-correction/retry logic wired (static check → retry loop) where
      the project's convention calls for it
- [ ] Model routing: agent's expected tier (Opus/Sonnet/Haiku) per
      `backend/app/fleet/agent_models.json` matches what `run_agent_graph()`
      actually resolves for it (trace through `model_router.py`)
- [ ] Fleet OS flags (`enable_planning`, `enable_memory`, `enable_reflection`,
      `enable_lesson`) are set deliberately, not left at stale defaults —
      cross-check against the agent's actual need (e.g. a pure-read auditor
      may not need `enable_lesson=True` if it never mutates code)
- [ ] `task_id` is threaded through to `run_agent_graph()` so activity-stream
      events and correct event correlation actually work (Day 18 finding —
      confirm this specific historical bug has not regressed for THIS agent)
- [ ] Dispatched from somewhere real: grep for the agent's run function
      (e.g. `run_bug_fix`) being called from `dispatcher.py`,
      `manager.py`, `specialized_agents.py`, or an API route. Flag any
      agent that exists, is registered, but is NEVER actually invoked from
      a real (non-test) code path — this exact pattern has recurred
      multiple times per PROJECT.md's own gap-closure sessions.

Produce a scorecard table: one row per agent, columns = the checklist above,
with ✅/❌/NOT FOUND per cell and a file:line citation for every ❌.

## PHASE 2 — Cross-Agent Consistency

- Diff the ~20 "read-only auditor" agents against each other — PROJECT.md
  states these deliberately share a minimal, uniform
  `set_by`/`enforce_in_result` pattern. Confirm this is actually uniform in
  code (not accidentally uniform, i.e. actually copy-pasted correctly) and
  flag any outlier.
- Confirm the "Karpathy principles" (Day 6A: CODING / REVIEW / DESIGN /
  ANALYSIS variants) are present in the correct variant for each role file's
  category — spot-check at least 15 across all 4 categories.
- Confirm no agent's tool list grants it capabilities forbidden by
  CLAUDE.md-level rules (no agent should have raw deploy/kubectl/production
  DB credentials — cross-check against `backend/app/policy/engine.py`'s
  denylist and confirm every coder-class agent's bash tool actually routes
  through that policy engine).

## PHASE 3 — Prompt Quality Spot-Audit

Pick 10 agents spanning different categories (coding, review, planning,
read-only-audit, docs) and for each:
- Does the role prompt give a concrete I/O contract, or is it vague?
- Does it contain any instruction that could cause prompt injection
  vulnerability (e.g. blindly trusting file contents as instructions)?
- Does it avoid contradicting `_GLOBAL_STANDARDS.md`?

## PHASE 3B — Deep Per-Agent Reliability Checklist

This phase goes beyond structural presence (Phase 1) into actual runtime
correctness. For each agent category below, spot-check at least 5 real
agents (more for coder-class, since they carry the most risk) and cite
file:line evidence for every answer — do not answer these from general
LLM-agent knowledge, answer them from what this specific codebase does.

**Model selection & fallback:**
- Does the agent's model come from `model_router.py` (correct), or is a
  model string hardcoded anywhere in the agent file, bypassing the router?
- Is there a fallback model/provider if the primary call fails (rate limit,
  timeout, 5xx)? Trace the actual retry/fallback code in `base.py` /
  `groq_adapter.py` — is fallback provider-level (Anthropic→OpenAI/Groq) or
  only retry-same-provider? State which, with evidence.
- Timeout policy: is there an actual enforced timeout on the LLM call
  itself (not just the overall run-time budget from `budget_manager`)? If
  the underlying SDK call has no explicit timeout, a hung connection could
  block a worker indefinitely — check for this specifically.

**Retry & self-correction:**
- For coder-class agents, is the retry loop bounded AND does each retry
  attempt actually change something (error fed back into context) rather
  than blindly re-running the same prompt?
- Confirm retry state doesn't leak between different tasks/runs (a stale
  retry counter reused across requests would be a real bug).

**Structured output & validation:**
- For every `submit_*` tool, is the payload validated against a Pydantic
  model before being trusted, or is `dict.get(...)` used with silent
  defaults on missing/malformed fields? Malformed-but-silently-defaulted
  output is a hallucination-propagation risk — flag it.
- Does JSON-parsing of LLM output (e.g. `executive.py`'s plain-JSON
  contract) have a real try/except with a meaningful error path, or does a
  malformed response crash the run ungracefully?

**Tool permissions & MCP-style permission matrix:**
- Build an actual matrix: agent × tool category (read/write/bash/git/
  network/destructive). Confirm no agent has a tool grant inconsistent with
  its role file's stated scope (e.g. a "read-only auditor" agent that
  somehow imports a write-capable tool list — cross-reference audit 02
  Phase 1's tool-scope check, this is the exhaustive version of it).
- For any external/network-calling tool (`web_search`, `http_request`,
  `github_create_pr`), confirm the calling agent's role file explicitly
  scopes what it's allowed to do with that access.

**Race conditions & concurrency safety (per-agent, not fleet-wide — audit
04 covers fleet-wide concurrency):**
- Does any agent handler mutate shared, non-request-scoped state (a module-
  level dict/list/counter) without a lock, in a way that could race under
  `MAX_CONCURRENT_AGENT_RUNS > 1`? `chat_agent.py`'s background-process
  tracking is a known-fixed instance per PROJECT.md (moved from module-level
  to per-instance) — confirm it's still per-instance, and check other
  agents for the same shape of bug.

**Inter-agent communication & memory synchronization:**
- When `run_manager()` hands a subtask from dev-agent to QA to Reviewer,
  what EXACTLY is passed between them (full diff? file list? summary
  only?)? Confirm nothing critical (e.g. the actual error text on a QA
  failure) is silently dropped between handoffs — trace one real failure
  path end to end.
- Confirm lesson/memory writes from one agent are actually visible to the
  next agent in the SAME run (not just future runs) where the design
  intends that — or confirm explicitly that it's next-run-only by design.

**Multimodal understanding (where applicable):**
- For the 4 agents wired to receive images (Day 16: pm/architect/
  frontend_dev/reviewer per PROJECT.md), confirm the image content block is
  actually included in the constructed message sent to the model — trace
  the exact `run_agent_graph(images=...)` call and the message-building
  code, don't just confirm the parameter exists.
- For PDF-reading tools (`read_pdf`), confirm the extracted text is bounded
  (not sending a 500-page PDF's full raw text unbounded into context).

**Emotion / intent understanding:**
- This project has no dedicated "user emotion" model — confirm that's
  actually true (no agent claims sentiment/emotion detection it doesn't
  have) rather than assuming based on category. If any role file's prompt
  claims to gauge user frustration/urgency, check whether that's backed by
  anything beyond prompt instruction (it's fine if it's prompt-only — just
  report it accurately rather than either crediting or dismissing it
  without checking).

## PHASE 4 — Final Report

1. Full agent scorecard (Phase 1 table)
2. Count: agents fully compliant / agents with gaps / agents NOT FOUND to
   have real callers
3. Capability tag collision findings (should be zero — prove it)
4. Tool-scope violations (read-only agents with write access, if any)
5. Dead/unreachable agents list
6. Model routing mismatches
7. Prompt quality spot-check findings
8. Prioritized fix list (Critical → Low), each with file:line
9. Overall Agent Layer Production-Readiness score (0-100)

Do not write code. Do not modify files.
