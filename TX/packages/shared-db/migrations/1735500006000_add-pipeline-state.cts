import type { MigrationBuilder } from "node-pg-migrate";

export const up = (pgm: MigrationBuilder): void => {
  // Pipeline state: persists PM→Architect→Decomposer planning results per task
  pgm.createTable("pipeline_state", {
    id: { type: "uuid", primaryKey: true, default: pgm.func("gen_random_uuid()") },
    task_id: { type: "uuid", notNull: true, unique: true, references: '"dev_tasks"', onDelete: "CASCADE" },
    stage: {
      type: "text",
      notNull: true,
      // pm_agent | architect_agent | task_decomposer | awaiting_approval | approved | rejected
    },
    pm_brief: { type: "jsonb", notNull: false },
    architect_plan: { type: "jsonb", notNull: false },
    subtasks: { type: "jsonb", notNull: false },
    error: { type: "text", notNull: false },
    created_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
    updated_at: { type: "timestamptz", notNull: true, default: pgm.func("now()") },
  });

  pgm.addIndex("pipeline_state", ["task_id"]);
};

export const down = (pgm: MigrationBuilder): void => {
  pgm.dropTable("pipeline_state");
};
