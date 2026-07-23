# ADR 005 — Direct in-process tool dispatch, not MCP, is the primary agent-to-tool path

**Status:** Accepted
**Date:** 2026-07-23

## Context

`docs/files/02_System_Architecture_Blueprint.md` and `docs/files/07_Tool_MCP_Specification.md`
both name the Model Context Protocol (MCP) as the intended mechanism for agent tool access —
"agents access tools through MCP servers, not custom one-off integrations." A real, working custom
MCP server exists in this codebase (`backend/app/mcp/server.py`) — a genuine stdio JSON-RPC 2.0
server exposing 4 repository-intelligence tools (`index_repository`, `search_symbols`,
`build_context`, `query_dependencies`) with real handler logic, not a stub.

A verified gap-closure audit (`files/GAPS_ALL_FILES_REPORT.md`, 2026-07-23) confirmed that despite
this, **none of the 72 real production agents actually call tools through MCP.** Every agent gets
its tools via direct in-process Python dispatch: schema definitions and handler functions in
`backend/app/agents/tools.py`, wired through `backend/app/agents/base.py` and
`backend/app/agents/base_graph.py`'s shared tool-execution loop. The MCP server is real and
invocable (`python -m app.mcp.server`), but has no caller anywhere in the running application —
confirmed by grep, not assumed.

## Decision

Direct in-process tool dispatch (`agents/tools.py` + `agents/base.py`/`base_graph.py`) **is and
remains** the real, primary path by which all 72 agents call tools. The existing MCP server stays
as real, tested, invocable code — useful if an external tool or a future standalone client ever
needs to discover Gridiron's repository-intelligence capabilities over the MCP protocol — but it is
not, and will not become, the internal agent-to-tool path.

We are **not** rebuilding the 72 agents' tool access to route through MCP.

## Rationale

This is the same category of decision as ADR-001 (custom Messages-API tool loop instead of the
Claude Agent SDK), and the reasoning is structurally identical:

- **Tools already work correctly today.** Every one of the 72 agents' tool calls is live, tested,
  and policy-enforced (`policy/engine.py`'s PreToolUse-style checks run at the same in-process
  dispatch call site, before every tool execution). There is no functional capability gap that
  routing through MCP would close.
- **Blast radius.** Rerouting tool access through MCP would touch every one of the 72 agent
  modules and every tool-call site in `agents/tools.py`, `agents/base.py`, and
  `agents/base_graph.py` — the single largest possible change surface in this codebase, against a
  currently-green 2700+-test suite.
- **Control over policy enforcement.** Our Policy Engine's PreToolUse-style denylist (`.env*`,
  `secrets/**`, dangerous bash commands) is trivially wired at the direct-dispatch call site today.
  Routing through MCP would mean either re-implementing that enforcement inside an MCP server
  boundary, or bridging back out to the same policy code from there — added indirection for the
  same guarantee we already have.
- **Migration risk vs. payoff.** As ADR-001 put it: "switching from a working implementation
  mid-project to an unfamiliar abstraction is high risk for zero functional gain." That reasoning
  applies here without modification.

## Consequences

- No functional change. This ADR documents an already-existing architecture, not a new one.
- `backend/app/mcp/server.py` remains real and maintained as a standalone capability (repo
  intelligence exposed over MCP for external consumers), independent of the internal agent tool
  path. It is not deprecated — just not the primary route.
- If a future need arises for external tools/IDEs to call Gridiron's repo-intelligence functions
  over MCP, this server is already there and already works — no new build required for that case.
- If a strong, specific reason emerges to migrate the internal 72-agent tool-call path to MCP
  (e.g., a real need for out-of-process tool execution, or third-party tool servers we don't want
  to reimplement), that is a deliberate, large-scope re-architecture requiring its own plan and
  explicit sign-off — not an incremental change to slot into routine gap-closure work.
