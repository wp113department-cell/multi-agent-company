# Composio — Research Notes (Phase 6)

**Date:** 2026-07-03

## Availability

The `/repos/composio` clone was not present in this environment at Phase 6 build time.
All architectural decisions for the Agent Registry are derived from:
- The MASTER_PROMPT_PACK Prompt 6 spec
- Direct inspection of the Gridiron LangGraph dispatcher (`pipeline/dispatcher.py`)
- SQLAlchemy JSONB + array patterns already used in `db/models.py`

## Composio Pattern (from prior research / public docs)

Composio is a tool-registry / integration layer for AI agents. Key patterns applicable to Gridiron:

1. **Tool registry by capability tag** — agents are looked up by what they can do, not by name.
   Gridiron applies this in `agents` table: `capability_tags TEXT[]` column.

2. **Metrics tracking per tool** — success_rate, avg_latency, usage_count tracked per registered agent.
   Gridiron: `success_rate float`, `avg_retries float`, `last_computed_at` in `agents` table.

3. **Tool manifest (JSON)** — each tool/agent declares its schema in a structured manifest.
   Gridiron: `tool_list JSONB` stores the list of tool names each agent exposes.

4. **Dynamic dispatch** — the orchestrator queries the registry, not hardcoded identifiers.
   Gridiron: `Dispatcher.pick_agent(tag)` → `SELECT * FROM agents WHERE :tag = ANY(capability_tags)`.

## Web-Search MCP

Checked: no web-search MCP server is configured in this environment.
`Research Agent` uses the `read_file`/`list_files` tools it is already granted access to.
A `web_search` placeholder tool is defined but returns a "not available" message when no MCP is wired.
When a web-search MCP is later added, replace the placeholder handler with the real MCP call.

## Decisions

- Agent Registry: `agents` table with UUID PK, capability_tags ARRAY, tool_list JSONB, metrics columns.
- Research Agent: tools = [read_file, list_files, web_search (placeholder)]. NO write/bash.
- Engineering Memory: pgvector 0.4.2 `Vector(1536)` column + Voyage AI embed on task completion.
  Falls back to zero-vector if VOYAGE_API_KEY not set (memory store still inserts row, search returns empty).
