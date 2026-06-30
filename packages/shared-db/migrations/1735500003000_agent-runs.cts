import type { MigrationBuilder } from "node-pg-migrate";

export async function up(pgm: MigrationBuilder): Promise<void> {
  pgm.createTable("agent_runs", {
    run_id: {
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
    agent_type: { type: "text", notNull: true },
    status: {
      type: "text",
      notNull: true,
      default: "created",
      check:
        "status IN ('created','planning','coding','testing','blocked','completed','failed')",
    },
    checkpoint_id: { type: "text" },
    started_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
    completed_at: { type: "timestamptz" },
  });

  pgm.createIndex("agent_runs", "task_id");
}

export async function down(pgm: MigrationBuilder): Promise<void> {
  pgm.dropTable("agent_runs");
}
