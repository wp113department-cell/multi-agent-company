import type { MigrationBuilder } from "node-pg-migrate";

export async function up(pgm: MigrationBuilder): Promise<void> {
  pgm.addColumns("agent_runs", {
    tokens_in: { type: "integer" },
    tokens_out: { type: "integer" },
    cost_estimate: { type: "numeric(10,6)" },
    last_heartbeat_at: { type: "timestamptz" },
    model_id: { type: "text" },
  });
}

export async function down(pgm: MigrationBuilder): Promise<void> {
  pgm.dropColumns("agent_runs", ["tokens_in", "tokens_out", "cost_estimate", "last_heartbeat_at", "model_id"]);
}
