import { query } from "@gridiron/shared-db";
import type { ArchitectPlan, PipelineStage, PipelineState, PmBrief, SubTask } from "./types";

interface PipelineRow {
  id: string;
  task_id: string;
  stage: string;
  pm_brief: PmBrief | null;
  architect_plan: ArchitectPlan | null;
  subtasks: SubTask[] | null;
  error: string | null;
  created_at: Date;
  updated_at: Date;
}

function rowToState(row: PipelineRow): PipelineState {
  return {
    id: row.id,
    taskId: row.task_id,
    stage: row.stage as PipelineStage,
    pmBrief: row.pm_brief,
    architectPlan: row.architect_plan,
    subtasks: row.subtasks,
    error: row.error,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function createPipelineState(taskId: string): Promise<PipelineState> {
  const result = await query<PipelineRow>(
    `INSERT INTO pipeline_state (task_id, stage)
     VALUES ($1, 'pm_agent')
     ON CONFLICT (task_id) DO UPDATE SET stage = 'pm_agent', updated_at = now()
     RETURNING *`,
    [taskId],
  );
  return rowToState(result.rows[0]!);
}

export async function getPipelineState(taskId: string): Promise<PipelineState | null> {
  const result = await query<PipelineRow>(
    `SELECT * FROM pipeline_state WHERE task_id = $1`,
    [taskId],
  );
  return result.rows[0] ? rowToState(result.rows[0]) : null;
}

export async function updatePipelineState(
  taskId: string,
  patch: Partial<{
    stage: PipelineStage;
    pmBrief: PmBrief;
    architectPlan: ArchitectPlan;
    subtasks: SubTask[];
    error: string;
  }>,
): Promise<PipelineState> {
  const sets: string[] = ["updated_at = now()"];
  const params: unknown[] = [];

  function set(col: string, val: unknown) {
    params.push(typeof val === "object" ? JSON.stringify(val) : val);
    sets.push(`${col} = $${params.length}`);
  }

  if (patch.stage !== undefined) set("stage", patch.stage);
  if (patch.pmBrief !== undefined) set("pm_brief", patch.pmBrief);
  if (patch.architectPlan !== undefined) set("architect_plan", patch.architectPlan);
  if (patch.subtasks !== undefined) set("subtasks", patch.subtasks);
  if (patch.error !== undefined) set("error", patch.error);

  params.push(taskId);
  const result = await query<PipelineRow>(
    `UPDATE pipeline_state SET ${sets.join(", ")} WHERE task_id = $${params.length} RETURNING *`,
    params,
  );
  return rowToState(result.rows[0]!);
}
