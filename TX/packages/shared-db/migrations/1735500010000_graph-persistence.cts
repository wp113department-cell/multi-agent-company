import type { MigrationBuilder } from "node-pg-migrate";

export async function up(pgm: MigrationBuilder): Promise<void> {
  // file index: tracks which files have been indexed and their content hash
  pgm.createTable("indexed_files", {
    file_id: {
      type: "uuid",
      primaryKey: true,
      default: pgm.func("gen_random_uuid()"),
    },
    repo_path: { type: "text", notNull: true },
    file_path: { type: "text", notNull: true },
    content_hash: { type: "text", notNull: true },
    last_indexed_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });
  pgm.addConstraint("indexed_files", "indexed_files_repo_file_unique", "UNIQUE(repo_path, file_path)");

  // symbol index: functions and classes extracted from indexed files
  pgm.createTable("symbols", {
    symbol_id: {
      type: "uuid",
      primaryKey: true,
      default: pgm.func("gen_random_uuid()"),
    },
    file_id: {
      type: "uuid",
      notNull: true,
      references: "indexed_files(file_id)",
      onDelete: "CASCADE",
    },
    name: { type: "text", notNull: true },
    kind: { type: "text", notNull: true, check: "kind IN ('function','class','method','interface','type')" },
    line_start: { type: "integer" },
    line_end: { type: "integer" },
  });
  pgm.createIndex("symbols", "file_id");
  pgm.createIndex("symbols", "name");

  // call graph edges: caller symbol → callee symbol
  pgm.createTable("call_edges", {
    edge_id: {
      type: "uuid",
      primaryKey: true,
      default: pgm.func("gen_random_uuid()"),
    },
    caller_id: {
      type: "uuid",
      notNull: true,
      references: "symbols(symbol_id)",
      onDelete: "CASCADE",
    },
    callee_name: { type: "text", notNull: true },
    callee_file: { type: "text" },
  });
  pgm.createIndex("call_edges", "caller_id");
}

export async function down(pgm: MigrationBuilder): Promise<void> {
  pgm.dropTable("call_edges");
  pgm.dropTable("symbols");
  pgm.dropTable("indexed_files");
}
