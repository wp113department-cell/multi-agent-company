import type { MigrationBuilder } from "node-pg-migrate";

export const up = (pgm: MigrationBuilder): void => {
  // Make chunk_index nullable (we use one embedding per file, not chunked)
  pgm.alterColumn("code_embeddings", "chunk_index", { type: "int", notNull: false });

  // Add content_hash for efficient dedup (skip files whose content hasn't changed)
  pgm.addColumn("code_embeddings", {
    content_hash: { type: "text", notNull: false },
  });

  // Add updated_at for tracking when an embedding was last refreshed
  pgm.addColumn("code_embeddings", {
    updated_at: { type: "timestamptz", notNull: false, default: pgm.func("now()") },
  });

  // Add unique constraint so ON CONFLICT (repo_path, file_path) works
  pgm.addConstraint("code_embeddings", "code_embeddings_repo_file_unique", "UNIQUE (repo_path, file_path)");
};

export const down = (pgm: MigrationBuilder): void => {
  pgm.dropConstraint("code_embeddings", "code_embeddings_repo_file_unique");
  pgm.dropColumn("code_embeddings", "updated_at");
  pgm.dropColumn("code_embeddings", "content_hash");
  pgm.alterColumn("code_embeddings", "chunk_index", { type: "int", notNull: true });
};
