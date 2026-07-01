import type { CreateTaskInput, DevTask, TaskLog, TaskStatus } from "@gridiron/shared-types";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchTasks(status?: string): Promise<DevTask[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`/api/tasks${qs}`, { cache: "no-store" });
  const data = await handleResponse<{ tasks: DevTask[] }>(res);
  return data.tasks;
}

export async function fetchTask(taskId: string): Promise<DevTask & { logs: TaskLog[] }> {
  const res = await fetch(`/api/tasks/${taskId}`, { cache: "no-store" });
  return handleResponse(res);
}

export async function createTask(input: CreateTaskInput): Promise<DevTask> {
  const res = await fetch(`/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return handleResponse(res);
}

export async function triggerAgentRun(taskId: string): Promise<{ message: string }> {
  const res = await fetch(`/api/tasks/${taskId}/run`, { method: "POST" });
  return handleResponse(res);
}

export async function updateTaskStatus(taskId: string, status: TaskStatus): Promise<DevTask> {
  const res = await fetch(`/api/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return handleResponse(res);
}

export interface PipelineStateClient {
  id: string;
  taskId: string;
  stage: string;
  pmBrief: unknown;
  architectPlan: unknown;
  subtasks: unknown;
  error: string | null;
  updatedAt: string;
}

export async function fetchPipelineState(taskId: string): Promise<PipelineStateClient | null> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline`, { cache: "no-store" });
  if (res.status === 404) return null;
  return handleResponse(res);
}

export async function triggerPipeline(taskId: string): Promise<{ message: string }> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline`, { method: "POST" });
  return handleResponse(res);
}

export async function approvePipeline(taskId: string): Promise<{ message: string }> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline/approve`, { method: "POST" });
  return handleResponse(res);
}

export async function rejectPipeline(taskId: string): Promise<{ message: string }> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline/reject`, { method: "POST" });
  return handleResponse(res);
}
