import type { MigrationBuilder } from "node-pg-migrate";

export async function up(pgm: MigrationBuilder): Promise<void> {
  pgm.createTable("subtasks", {
    subtask_id: {
      type: "text",
      primaryKey: true,
    },
    task_id: {
      type: "uuid",
      notNull: true,
      references: "dev_tasks(task_id)",
      onDelete: "CASCADE",
    },
    type: {
      type: "text",
      notNull: true,
      check: "type IN ('backend','frontend','test','docs','config','migration')",
    },
    title: { type: "text", notNull: true },
    description: { type: "text", notNull: true },
    files_to_edit: { type: "text[]", notNull: true, default: pgm.func("ARRAY[]::text[]") },
    depends_on: { type: "text[]", notNull: true, default: pgm.func("ARRAY[]::text[]") },
    status: {
      type: "text",
      notNull: true,
      default: "pending",
      check: "status IN ('pending','in_progress','done','blocked')",
    },
    created_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });

  pgm.createIndex("subtasks", "task_id");
}

export async function down(pgm: MigrationBuilder): Promise<void> {
  pgm.dropTable("subtasks");
}
