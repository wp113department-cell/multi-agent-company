# OpenHands — Architectural Reference Notes

Source: `/repos/open-hands/openhands/`

## Session & App Architecture

- FastAPI app in `app_server/app.py` with an async lifespan (`get_app_lifespan_service`)
- Sessions are ephemeral but MCP integration is wired at startup, not per-request
- MCP server mounted via `mcp_server.http_app` — treated as a sub-app, not a separate process
- Session manager keeps agent state in memory; persistence is event-log based

## Agent Loop Pattern

- Each agent has a `step()` method returning an `Action` object (not a string)
- Actions are typed: `CmdRunAction`, `FileWriteAction`, `BrowseURLAction`, `AgentFinishAction`
- Observations are typed responses: `CmdOutputObservation`, `FileReadObservation`
- Loop: `agent.step(state)` → `action` → execute → `observation` → append to state → repeat

## What Gridiron Borrows

- **Typed action/observation pattern**: our `AgentTool` execute() returning string is weaker — typed return objects would enable better logging and policy checks
- **Event log as persistence**: append-only log is more resilient than mutable state
- **MCP as sub-app**: our MCP server runs as a separate process (stdio); HTTP mounting would allow same-process integration if needed in future
- **Session isolation**: each task gets isolated state — matches our worktree isolation model

## What We Do Differently (and why)

- We use Anthropic tool-use natively (not a custom action DSL) — simpler, fewer layers
- We persist task state to Postgres rather than in-memory sessions — survives restarts
- We don't implement a browser agent — out of scope for Phase 0-3
