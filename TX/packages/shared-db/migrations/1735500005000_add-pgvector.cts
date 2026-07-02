import type { MigrationBuilder } from "node-pg-migrate";

export const up = (pgm: MigrationBuilder): void => {
  // Enable pgvector extension (requires superuser privileges)
  // NOTE: If using Supabase, pgvector is pre-installed. For local Postgres,
  // run: CREATE EXTENSION vector; as superuser before migrating.
  pgm.sql(`CREATE EXTENSION IF NOT EXISTS vector`);

  // Code embeddings: chunks of code with their vector embeddings
  pgm.createTable("code_embeddings", {
    id: { type: "uuid", primaryKey: true, default: pgm.func("gen_random_uuid()") },
    repo_path: { type: "text", notNull: true },
    file_path: { type: "text", notNull: true },
    chunk_index: { type: "int", notNull: true },
    content: { type: "text", notNull: true },
    embedding: { type: "vector(1536)", notNull: false },
    created_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });

  pgm.addIndex("code_embeddings", ["repo_path", "file_path"]);

  // Repo index entries: symbol/file graph persisted to DB for cross-session reuse
  pgm.createTable("repo_index_entries", {
    id: { type: "uuid", primaryKey: true, default: pgm.func("gen_random_uuid()") },
    repo_path: { type: "text", notNull: true },
    file_path: { type: "text", notNull: true },
    entry_type: { type: "text", notNull: true },
    name: { type: "text", notNull: false },
    metadata: { type: "jsonb", notNull: false },
    created_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });

  pgm.addIndex("repo_index_entries", ["repo_path", "file_path"]);
  pgm.addIndex("repo_index_entries", ["repo_path", "entry_type"]);
};

export const down = (pgm: MigrationBuilder): void => {
  pgm.dropTable("repo_index_entries");
  pgm.dropTable("code_embeddings");
  pgm.sql(`DROP EXTENSION IF EXISTS vector`);
};
