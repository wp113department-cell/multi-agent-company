import type { CreateTaskInput, DevTask, TaskLog } from "@gridiron/shared-types";

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
