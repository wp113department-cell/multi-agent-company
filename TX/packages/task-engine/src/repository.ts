import { query } from "@gridiron/shared-db";
import {
  type AgentRun,
  type AgentRunStatus,
  type CreateTaskInput,
  type CreateTaskLogInput,
  type DevTask,
  type TaskLog,
  type TaskStatus,
  type UpdateTaskInput,
} from "@gridiron/shared-types";
import { assertValidTransition } from "./status-transitions";

// --- row <-> domain mapping -------------------------------------------------

interface DevTaskRow {
  task_id: string;
  title: string;
  description: string | null;
  priority: string;
  status: string;
  assigned_agent: string | null;
  project: string | null;
  files_touched: string[];
  plan: string | null;
  diff: string | null;
  final_summary: string | null;
  created_at: Date;
  updated_at: Date;
}

function rowToDevTask(row: DevTaskRow): DevTask {
  return {
    taskId: row.task_id,
    title: row.title,
    description: row.description,
    priority: row.priority as DevTask["priority"],
    status: row.status as DevTask["status"],
    assignedAgent: row.assigned_agent,
    project: row.project,
    filesTouched: row.files_touched ?? [],
    plan: row.plan,
    diff: row.diff,
    finalSummary: row.final_summary,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

interface TaskLogRow {
  log_id: string;
  task_id: string;
  category: string;
  message: string;
  metadata: Record<string, unknown> | null;
  created_at: Date;
}

function rowToTaskLog(row: TaskLogRow): TaskLog {
  return {
    logId: row.log_id,
    taskId: row.task_id,
    category: row.category as TaskLog["category"],
    message: row.message,
    metadata: row.metadata,
    createdAt: row.created_at,
  };
}

interface AgentRunRow {
  run_id: string;
  task_id: string;
  agent_type: string;
  model_id: string | null;
  status: string;
  checkpoint_id: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_estimate: string | null;
  last_heartbeat_at: Date | null;
  started_at: Date;
  completed_at: Date | null;
}

function rowToAgentRun(row: AgentRunRow): AgentRun {
  return {
    runId: row.run_id,
    taskId: row.task_id,
    agentType: row.agent_type,
    modelId: row.model_id,
    status: row.status as AgentRunStatus,
    checkpointId: row.checkpoint_id,
    tokensIn: row.tokens_in,
    tokensOut: row.tokens_out,
    costEstimate: row.cost_estimate !== null ? parseFloat(row.cost_estimate) : null,
    lastHeartbeatAt: row.last_heartbeat_at,
    startedAt: row.started_at,
    completedAt: row.completed_at,
  };
}

// --- dev_tasks ---------------------------------------------------------------

export async function createTask(input: CreateTaskInput): Promise<DevTask> {
  const result = await query<DevTaskRow>(
    `INSERT INTO dev_tasks (title, description, priority, project, status)
     VALUES ($1, $2, $3, $4, 'pending')
     RETURNING *`,
    [input.title, input.description ?? null, input.priority, input.project ?? null],
  );
  return rowToDevTask(result.rows[0]!);
}

export interface ListTasksFilter {
  status?: TaskStatus;
  project?: string;
  cursor?: string;
  limit?: number;
}

export async function listTasks(filter: ListTasksFilter = {}): Promise<DevTask[]> {
  const limit = Math.min(filter.limit ?? 20, 100);
  const conditions: string[] = [];
  const params: unknown[] = [];

  if (filter.status) {
    params.push(filter.status);
    conditions.push(`status = $${params.length}`);
  }
  if (filter.project) {
    params.push(filter.project);
    conditions.push(`project = $${params.length}`);
  }
  if (filter.cursor) {
    params.push(filter.cursor);
    conditions.push(`task_id < $${params.length}`);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  params.push(limit);

  const result = await query<DevTaskRow>(
    `SELECT * FROM dev_tasks ${where} ORDER BY created_at DESC LIMIT $${params.length}`,
    params,
  );
  return result.rows.map(rowToDevTask);
}

export async function getTask(taskId: string): Promise<DevTask | null> {
  const result = await query<DevTaskRow>(`SELECT * FROM dev_tasks WHERE task_id = $1`, [taskId]);
  return result.rows[0] ? rowToDevTask(result.rows[0]) : null;
}

export async function updateTask(taskId: string, input: UpdateTaskInput): Promise<DevTask> {
  const current = await getTask(taskId);
  if (!current) {
    throw new Error(`Task not found: ${taskId}`);
  }
  if (input.status) {
    assertValidTransition(current.status, input.status);
  }

  const sets: string[] = [];
  const params: unknown[] = [];

  function set(column: string, value: unknown) {
    params.push(value);
    sets.push(`${column} = $${params.length}`);
  }

  if (input.status !== undefined) set("status", input.status);
  if (input.assignedAgent !== undefined) set("assigned_agent", input.assignedAgent);
  if (input.filesTouched !== undefined) set("files_touched", JSON.stringify(input.filesTouched));
  if (input.plan !== undefined) set("plan", input.plan);
  if (input.diff !== undefined) set("diff", input.diff);
  if (input.finalSummary !== undefined) set("final_summary", input.finalSummary);
  sets.push(`updated_at = now()`);

  params.push(taskId);
  const result = await query<DevTaskRow>(
    `UPDATE dev_tasks SET ${sets.join(", ")} WHERE task_id = $${params.length} RETURNING *`,
    params,
  );
  return rowToDevTask(result.rows[0]!);
}

// --- task_logs -----------------------------------------------------------------

export async function appendTaskLog(taskId: string, input: CreateTaskLogInput): Promise<TaskLog> {
  const result = await query<TaskLogRow>(
    `INSERT INTO task_logs (task_id, category, message, metadata)
     VALUES ($1, $2, $3, $4)
     RETURNING *`,
    [taskId, input.category, input.message, input.metadata ? JSON.stringify(input.metadata) : null],
  );
  return rowToTaskLog(result.rows[0]!);
}

export async function listTaskLogs(taskId: string): Promise<TaskLog[]> {
  const result = await query<TaskLogRow>(
    `SELECT * FROM task_logs WHERE task_id = $1 ORDER BY created_at ASC`,
    [taskId],
  );
  return result.rows.map(rowToTaskLog);
}

// --- agent_runs ----------------------------------------------------------------

export async function createAgentRun(taskId: string, agentType: string): Promise<AgentRun> {
  const result = await query<AgentRunRow>(
    `INSERT INTO agent_runs (task_id, agent_type, status) VALUES ($1, $2, 'created') RETURNING *`,
    [taskId, agentType],
  );
  return rowToAgentRun(result.rows[0]!);
}

export async function updateAgentRun(
  runId: string,
  status: AgentRunStatus,
  completedAt?: Date,
): Promise<AgentRun> {
  const result = await query<AgentRunRow>(
    `UPDATE agent_runs SET status = $1, completed_at = $2 WHERE run_id = $3 RETURNING *`,
    [status, completedAt ?? null, runId],
  );
  return rowToAgentRun(result.rows[0]!);
}

export async function listAgentRuns(taskId: string): Promise<AgentRun[]> {
  const result = await query<AgentRunRow>(
    `SELECT * FROM agent_runs WHERE task_id = $1 ORDER BY started_at DESC`,
    [taskId],
  );
  return result.rows.map(rowToAgentRun);
}

// --- subtasks ------------------------------------------------------------------

export interface SubTaskRecord {
  subtaskId: string;
  taskId: string;
  type: string;
  title: string;
  description: string;
  filesToEdit: string[];
  dependsOn: string[];
  status: "pending" | "in_progress" | "done" | "blocked";
  createdAt: Date;
}

export async function saveSubtasks(
  taskId: string,
  subtasks: Array<{
    id: string;
    type: string;
    title: string;
    description: string;
    filesToEdit: string[];
    dependsOn: string[];
  }>,
): Promise<void> {
  if (subtasks.length === 0) return;
  for (const s of subtasks) {
    await query(
      `INSERT INTO subtasks (subtask_id, task_id, type, title, description, files_to_edit, depends_on)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (subtask_id) DO UPDATE
         SET title = EXCLUDED.title,
             description = EXCLUDED.description,
             files_to_edit = EXCLUDED.files_to_edit,
             depends_on = EXCLUDED.depends_on`,
      [s.id, taskId, s.type, s.title, s.description, s.filesToEdit, s.dependsOn],
    );
  }
}

export async function listSubtasks(taskId: string): Promise<SubTaskRecord[]> {
  interface SubtaskRow {
    subtask_id: string;
    task_id: string;
    type: string;
    title: string;
    description: string;
    files_to_edit: string[];
    depends_on: string[];
    status: string;
    created_at: Date;
  }
  const result = await query<SubtaskRow>(
    `SELECT * FROM subtasks WHERE task_id = $1 ORDER BY created_at ASC`,
    [taskId],
  );
  return result.rows.map((r) => ({
    subtaskId: r.subtask_id,
    taskId: r.task_id,
    type: r.type,
    title: r.title,
    description: r.description,
    filesToEdit: r.files_to_edit,
    dependsOn: r.depends_on,
    status: r.status as SubTaskRecord["status"],
    createdAt: r.created_at,
  }));
}

// --- agent_runs heartbeat/tokens -----------------------------------------------

export async function heartbeatAgentRun(runId: string): Promise<void> {
  await query(`UPDATE agent_runs SET last_heartbeat_at = now() WHERE run_id = $1`, [runId]);
}

export async function recordAgentRunTokens(
  runId: string,
  tokensIn: number,
  tokensOut: number,
  costEstimate: number,
): Promise<void> {
  await query(
    `UPDATE agent_runs SET tokens_in = $1, tokens_out = $2, cost_estimate = $3 WHERE run_id = $4`,
    [tokensIn, tokensOut, costEstimate, runId],
  );
}
