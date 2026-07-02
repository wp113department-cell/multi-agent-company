# ADR 003 — Git worktrees for agent isolation, not Docker containers

**Status:** Accepted  
**Date:** 2026-06-01

## Context

The coding agent must be isolated so it cannot accidentally corrupt the main working tree. Options:
1. **Git worktrees** — `git worktree add` creates a separate checkout of the repo
2. **Docker containers** — full filesystem isolation with a container per task
3. **VM / sandbox** — strongest isolation, most complex

## Decision

We use `git worktree add` (via `packages/agent-runtime/src/worktree.ts`) to create an isolated checkout per task in `WORKTREES_DIR/task-{id}`.

## Rationale

- **Zero infrastructure overhead**: no Docker daemon, no container build time, no image pull
- **Shared git objects**: worktrees share `.git` history — branching, diffing, and merging are instant
- **Sufficient isolation**: the policy engine blocks the agent from writing outside its worktree path — git worktree boundaries enforce the filesystem scope
- **Easy cleanup**: `git worktree remove --force` is all it takes
- **Human review flow**: the worktree branch can be diffed and merged by a human without any container export step

## Consequences

- Isolation is at the process/path level, not the OS level — a sufficiently adversarial prompt could escape if policy-engine checks are bypassed
- For Phase 0-3, policy-engine denylist + worktree path scoping is the security boundary
- Container-level isolation remains an option for future phases if threat model demands it
- `WORKTREES_DIR` is configurable (env var) — defaults to `/tmp/gridiron/worktrees` for development, can be set to a dedicated volume in production
