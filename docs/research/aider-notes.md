# Aider — Architectural Reference Notes

Source: `/repos/aider/aider/repomap.py`

## RepoMap Approach

- `RepoMap` class builds a token-budget-aware summary of the repo for the LLM context window
- Uses `tree-sitter` (via `grep_ast`) to extract tags (functions, classes, symbols) from source files
- Tags are `namedtuple("Tag", "rel_fname fname line name kind")` — minimal, flat structure
- Results are cached in SQLite (`.aider.tags.cache.v4/`) keyed by file hash — incremental by default
- Map is recomputed only for changed files; unchanged files reuse cached tags
- `map_tokens` parameter controls how many tokens the map is allowed to consume

## Key Design Decisions

- **Token budget enforcement at map level**: the map is truncated to fit within `map_tokens` — context window is treated as a first-class constraint
- **Disk-cached tag extraction**: tree-sitter parsing is expensive; caching by file hash makes re-indexing O(changed files)
- **Language detection via `filename_to_lang`**: handles polyglot repos without configuration
- **`map_mul_no_files=8`**: when no files are in context, the map is 8x larger — gives the LLM full repo awareness to pick files

## What Gridiron Borrows

- **Hash-based incremental indexing**: our `repo-intelligence` package should check file mtime/hash before re-embedding — avoids re-processing unchanged files (this is the "incremental re-index" gap)
- **Token budget as first-class constraint**: our `CONTEXT_BUDGET_CHARS` config does this at char level; same principle
- **SQLite tag cache**: our call graph (ts-morph) is recomputed fully on each reindex — adding a hash-keyed cache would make it much faster

## What We Do Differently

- We use pgvector for semantic search (embedding similarity), not just tag-based grep — better for "find code related to X" queries
- Our context builder combines graph + embeddings + file content, not just a repo map string
- We don't use tree-sitter directly (ts-morph wraps the TypeScript compiler API, which is more accurate for TS)
