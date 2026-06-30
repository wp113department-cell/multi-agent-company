# 10 — Repository Intelligence Specification

**Applies from:** Stage 3
**Related:** `02_System_Architecture_Blueprint.md`, `11_Memory_System_Specification.md`, `06_Agent_SDK_Specification.md`

---

## Purpose

The Repository Intelligence Service is what lets agents answer "what does this system touch?" instead of guessing from keyword search. It's built as a standalone internal service from the start — not a feature buried inside one agent — so any future internal tool can query it, not only the Developer Department's agents.

## Components

**Repository Scanner** — walks the codebase on first index and on a schedule/webhook trigger thereafter, identifying files, folders, and language boundaries.

**AST Parser** — uses Tree-sitter to parse each file into its abstract syntax tree, extracting functions, classes, and their signatures.

**Dependency / Import Graph** — maps which files import which other files, and which packages each file depends on.

**Call Graph** — maps which functions call which other functions, across file boundaries.

**Symbol Graph** — indexes every named entity (function, class, interface, type) and where it's defined and referenced.

**Embedding Search** — code and documentation summaries embedded into pgvector (Stage 3) for semantic "find something like X" queries, complementing the structural graph above.

**Architecture Mapper** — derives a higher-level view from the graphs above: which services/modules a given file or feature area belongs to (e.g., "the email discovery system" maps to a known set of files and workers).

**Context Builder** — the consumer-facing layer. Given a task description, it queries the graph and embedding store, and returns a focused, relevant context package (`{ relevantFiles, dependencies, summary }`) instead of every agent independently deciding what to read. This keeps token usage and accuracy consistent across all agents. Includes a **Context Cache**: once Backend Agent has resolved context for a task, QA Agent and Code Review Agent reuse it rather than redundantly re-indexing the same files.

## Recommended Implementation

Rather than building a custom indexer from scratch, the service is built on an existing open-source, MCP-native, AST-based code graph engine (Tree-sitter parsing into an embedded graph database), run fully locally so no code leaves Gridiron's infrastructure. This is faster to stand up, more reliable, and already exposes results over MCP directly to agents. Commercial managed context engines are a future option to re-evaluate only if accuracy on the real Gridiron codebase falls short of what the self-hosted engine delivers.

## MCP Interface

The service exposes its capabilities as MCP tools (e.g., `query_dependencies(file)`, `query_call_graph(function)`, `search_semantic(query)`), consumed by the Architect Agent and the Context Builder. Other internal tools (not just dev agents) can connect to the same MCP server if a future use case needs it.

## Update / Re-Index Strategy

Incremental re-indexing on every merge to `main` (only changed files are re-parsed, not the full repo) plus a full re-index on a weekly schedule as a consistency check. Re-indexing must complete before an Architect Agent run is allowed to start on a task touching recently changed files, to avoid planning against stale graph data.

## Definition of Done (Stage 3)

Given a real feature request like "improve worker queue status visibility," the Architect Agent's list of impacted files is verifiably correct against the actual codebase — not a plausible-sounding guess.
