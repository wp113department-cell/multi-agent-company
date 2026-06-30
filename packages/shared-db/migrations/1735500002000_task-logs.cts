import type { MigrationBuilder } from "node-pg-migrate";

export async function up(pgm: MigrationBuilder): Promise<void> {
  pgm.createTable("task_logs", {
    log_id: {
      type: "uuid",
      primaryKey: true,
      default: pgm.func("gen_random_uuid()"),
    },
    task_id: {
      type: "uuid",
      notNull: true,
      references: "dev_tasks(task_id)",
      onDelete: "CASCADE",
    },
    category: { type: "text", notNull: true },
    message: { type: "text", notNull: true },
    metadata: { type: "jsonb" },
    created_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });

  pgm.createIndex("task_logs", ["task_id", "created_at"]);
}

export async function down(pgm: MigrationBuilder): Promise<void> {
  pgm.dropTable("task_logs");
}
