import { query } from "@gridiron/shared-db";
import {
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
