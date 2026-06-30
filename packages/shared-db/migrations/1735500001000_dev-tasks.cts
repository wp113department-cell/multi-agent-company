import type { MigrationBuilder } from "node-pg-migrate";

export async function up(pgm: MigrationBuilder): Promise<void> {
  pgm.createExtension("pgcrypto", { ifNotExists: true });

  pgm.createTable("dev_tasks", {
    task_id: {
      type: "uuid",
      primaryKey: true,
      default: pgm.func("gen_random_uuid()"),
    },
    title: { type: "text", notNull: true },
    description: { type: "text" },
    priority: {
      type: "text",
      notNull: true,
      default: "medium",
      check: "priority IN ('low','medium','high')",
    },
    status: {
      type: "text",
      notNull: true,
      default: "pending",
      // Extends 09_Database_Design_Specification.md's enum with
      // 'ready_for_review' and 'rejected' — see shared-types/src/dev-task.ts
      // for why.
      check:
        "status IN ('pending','planning','ready_for_review','coding','testing','blocked','completed','failed','rejected')",
    },
    assigned_agent: { type: "text" },
    project: { type: "text" },
    files_touched: { type: "jsonb", notNull: true, default: "[]" },
    plan: { type: "text" },
    final_summary: { type: "text" },
    created_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
    updated_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });

  pgm.createIndex("dev_tasks", "status");
  pgm.createIndex("dev_tasks", "project");
}

export async function down(pgm: MigrationBuilder): Promise<void> {
  pgm.dropTable("dev_tasks");
}
