# Continue — Architectural Reference Notes

Source: `/repos/continue/core/indexing/LanceDbIndex.ts`

## Embedding + Vector Index Architecture

- `LanceDbIndex` wraps LanceDB (columnar vector store) for code embeddings
- Each row: `{ uuid, path, cachekey, vector: number[], ...metadata }`
- `cachekey` = hash of file content — used to detect staleness without re-reading all vectors
- Chunking is a separate step (`chunkDocument`) before embedding — chunks are the unit of retrieval, not whole files
- `artifactId = "vectordb::{embeddingsProvider.embeddingId}"` — each embedding model gets its own index, so switching models doesn't corrupt existing data

## Chunking Strategy

```typescript
// From chunk/chunk.js pattern:
// - Split file into overlapping windows (e.g. 512 tokens, 64-token overlap)
// - Each chunk gets its own embedding
// - Retrieval returns top-K chunks, then expands to surrounding context
```

- `basicChunker` for plain text; language-aware chunkers for code (split on function/class boundaries)
- `shouldChunk(file)` guards — binary files, auto-generated files, and very large files are skipped

## Indexing Lifecycle

1. `RefreshIndexResults` tells the indexer which paths are new/updated/deleted
2. New paths → chunk → embed → upsert into LanceDB
3. Updated paths → re-chunk → re-embed → replace by `cachekey`
4. Deleted paths → remove by path

## What Gridiron Borrows

- **`cachekey` (content hash) for incremental indexing**: our `repo-intelligence` package should store a `content_hash` alongside each embedding so re-index skips unchanged files
- **Chunking before embedding**: we currently embed whole files — chunking would improve retrieval precision for large files
- **`shouldChunk` guard**: we should skip binary files, `node_modules`, lock files, and auto-generated files
- **Per-model artifact isolation**: if we switch from `voyage-code-2`, old embeddings in the `code_embeddings` table should be invalidated — a `model_id` column achieves this

## What We Do Differently

- We use pgvector (Postgres extension) instead of LanceDB — fits our existing Postgres-first architecture, no extra service to manage
- We use Voyage AI (`voyage-code-2`) specifically tuned for code, not a generic embeddings model
- Our retrieval is query-time (REST API call) rather than IDE-integrated continuous indexing
