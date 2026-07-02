# Cline — Architectural Reference Notes

Source: `/repos/cline/apps/vscode/src/shared/AutoApprovalSettings.ts`

## Auto-Approval / Human-in-the-Loop Model

Cline has a granular per-action approval system:

```typescript
interface AutoApprovalSettings {
  actions: {
    readFiles: boolean        // read-only ops — auto-approved by default
    editFiles: boolean        // file writes — auto-approved by default
    executeSafeCommands: boolean  // "safe" shell commands — OFF by default
    executeAllCommands: boolean   // any shell command — ON by default (legacy)
    useBrowser: boolean
    useMcp: boolean
  }
  enableNotifications: boolean
}
```

- Default: read + edit + MCP = auto-approved; shell commands require explicit configuration
- `version` field on settings enables optimistic concurrency (race condition prevention)
- "Legacy" fields kept for backwards compatibility — good pattern for evolving config schemas

## Plan/Act Separation

- Cline distinguishes "plan" mode (thinking, no side effects) from "act" mode (tool calls with effects)
- In plan mode, the agent reasons about what to do; in act mode it executes
- This prevents premature tool calls during reasoning and makes the approval boundary clear

## What Gridiron Borrows

- **Per-action approval granularity**: our policy engine currently has a denylist (block dangerous patterns); adding an `AutoApprovalPolicy` with per-action flags would make it configurable without code changes
- **Plan/Act separation**: our PM → Architect → Decomposer pipeline is our "plan" phase; coding agent is "act" — keeping these strictly separated prevents the coding agent from reasoning about scope during execution
- **Notification setting**: we should log to `task_logs` when an action requires human approval (status `blocked`) with the specific action that triggered the block

## What We Do Differently

- We're server-side (no VSCode extension) — approval flows through the REST API (`/api/tasks/:id/approve`)
- Our worktree isolation is stronger than Cline's — all writes are confined to a git worktree, not the live workspace
- We don't implement browser use — out of scope
