# 07 — Tool / MCP Specification

**Applies from:** Stage 1, expanded through Stage 4
**Related:** `06_Agent_SDK_Specification.md`, `13_Policy_Engine_Specification.md`

---

## Principle

Tools are standardized through MCP (Model Context Protocol), not built as one-off custom integrations per agent. If a capability an agent needs already exists as an MCP server (filesystem, git, GitHub, Postgres, web search), it's used directly rather than reimplemented. Custom MCP servers are only written for genuinely Gridiron-specific needs — primarily the Repository Intelligence Service (`10_Repository_Intelligence_Specification.md`).

## MCP Servers In Use

| Server | Purpose | Introduced |
|---|---|---|
| Filesystem MCP | Read/list files within the worktree | Stage 1 |
| Git MCP | Inspect history, diffs, branches | Stage 1 |
| GitHub MCP | Read issues/PRs (Research Agent), create PRs (later stages) | Stage 1 (read), Stage 6 (write, Research Agent) |
| Postgres MCP | Read schema/data where an agent legitimately needs DB context | Stage 3+ |
| Repository Intelligence MCP (custom) | Query the AST/dependency graph | Stage 3 |
| Web Search | Research Agent's external research | Stage 6 |

## Tool Access Matrix

| Agent Role | Read | Edit/Write | Bash | Deploy |
|---|---|---|---|---|
| Planner / PM / Architect | ✅ | ❌ | ❌ | ❌ |
| Backend / Frontend Dev | ✅ | ✅ (worktree only) | ✅ (scoped: typecheck/lint/test only) | ❌ |
| QA Agent | ✅ | ❌ | ✅ (test/build commands only) | ❌ |
| Code Review Agent | ✅ | ❌ | ❌ | ❌ |
| Documentation Agent | ✅ | ✅ (`*.md` and doc folders only) | ❌ | ❌ |
| DevOps Agent | ✅ | ❌ | ✅ (read-only health checks only) | ❌ — no role ever gets this |
| Research Agent | ✅ (web + GitHub read) | ❌ | ❌ | ❌ |
| Manager / Executive Agent | ✅ | ❌ (delegates, doesn't edit directly) | ❌ | ❌ |

No deploy credentials are ever exposed to any agent's tool list, at any stage, by any role — see `05`, ADR-010.

## Adding a New Tool — Checklist

Confirm an existing public MCP server doesn't already cover the need (search the MCP registry first). If a custom server is genuinely required, define its scope narrowly (one capability, not a grab-bag), write it as its own package under `packages/`, and register which agent roles are allowed to use it. Every new tool addition must be reflected in the Tool Access Matrix above and reviewed against the Policy Engine (`13_Policy_Engine_Specification.md`) for whether it needs a guardrail.

## Tool Safety Integration

Every Write/Edit/Bash tool call passes through the Policy Engine's PreToolUse hook before execution (full spec in `13`). This is enforced at the application layer — denylisted paths and commands are rejected in code, not by prompt instruction, regardless of which agent or role is making the call.
