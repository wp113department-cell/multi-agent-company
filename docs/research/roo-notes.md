# Roo-Code Architecture Notes — Phase 4 Reference

Source: `/home/pc-117/Documents/CRR2906/repos/roo-code`

## Mode Separation Pattern

Roo separates agent responsibilities into **modes**. Each mode has:
- `slug` — machine identifier ("code", "architect", "debug", "ask")
- `name` — human label
- `groups` — tool groups the mode can access (e.g. `["read", "edit", "browser", "command"]`)
- `roleDefinition` — system prompt extension specific to the role

Tool access is **structurally enforced**: `getToolsForMode(mode.groups)` produces the exact tool list
passed to the model. A mode with no "edit" group literally cannot call write/edit tools — it's not in the
list. No amount of prompt text can override this.

## Tool Groups (from `src/shared/tools.ts` pattern)

```
TOOL_GROUPS = {
  "read":    [read_file, list_files, search_files, ...],
  "edit":    [write_to_file, apply_diff, ...],
  "browser": [browser_action],
  "command": [execute_command],
  "mcp":     [use_mcp_tool, access_mcp_resource],
}
ALWAYS_AVAILABLE_TOOLS = [ask_followup_question, attempt_completion, ...]
```

Architect mode: `["read", "browser"]` — can read and research, but structurally has no write or command tools.
Code mode: `["read", "edit", "browser", "command"]` — full access.
Debug mode: `["read", "browser", "command"]` — can run commands to diagnose, no writes.

## Custom Modes via Registry

`CustomModesManager` lets users register new modes via JSON config. Each custom mode:
- Extends `ModeConfig` schema — same fields as built-in modes
- Merged with built-in modes via `getAllModes(customModes)` — custom overrides built-in by slug

This maps to our `backend/roles/*.md` + `TOOL_SPEC` constant per agent module pattern.

## Key Lessons for Gridiron

1. **Tool list = the enforcement point.** Pass only the tools the role is allowed to use. Not documented in prompt.
2. **Mode config is declarative.** Define `slug → tool_groups` mapping once; tool list is derived, not repeated per agent.
3. **SwitchModeTool** — agents can request a mode switch (e.g., Code mode calls Architect for a design question). We model this as the Dispatcher routing subtasks to the right specialist.
4. **Role file = system prompt extension**, not full replacement. Our `backend/roles/*.md` files follow this: base safety rules come from `base.py` (load_role()), role file adds specialist guidance.
