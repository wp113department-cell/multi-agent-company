# ADR 001 — Use Anthropic Messages API directly, not Claude Agent SDK

**Status:** Accepted  
**Date:** 2026-06-01

## Context

The MASTER_PROMPT_PACK referenced "Claude Agent SDK `query()`" as the agent invocation primitive. The Anthropic ecosystem provides two options:

1. **`@anthropic-ai/sdk` Messages API with tool-use loop** — direct HTTP wrapper, full control over the conversation loop
2. **Claude Agent SDK** — higher-level abstraction with built-in tool orchestration

## Decision

We use `@anthropic-ai/sdk` with a custom `runAgentLoop()` in `packages/agent-runtime/src/base-agent.ts`, not the Claude Agent SDK.

## Rationale

- At time of implementation, Claude Agent SDK had limited TypeScript types — coding against its internals would require trusting memory rather than reading real types (violates ZERO HALLUCINATION RULES)
- The Messages API tool-use pattern is stable, well-typed, and completely documented in source
- Our policy-engine integration (checking every tool call before execution) is trivially wired at the `tool.execute()` call site — this would require monkey-patching or hooks in the Agent SDK
- Worktree isolation, retry counting, and `task_logs` appending are all in our loop — no SDK abstractions to fight
- Migration risk: switching from a working implementation mid-project to an unfamiliar abstraction is high risk for zero functional gain

## Consequences

- We maintain our own `runAgentLoop()` — ~100 lines, well-understood
- If Claude Agent SDK stabilizes and offers clear advantages (better streaming, built-in MCP routing), we can migrate one agent at a time without changing the interface
- All agents are real Anthropic API calls with real tool-use — no mocked responses
