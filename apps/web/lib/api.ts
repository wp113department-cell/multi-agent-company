// All fetches go to /api/* which Next.js proxies to http://localhost:8000/api/*
// via the rewrites() in next.config.mjs.

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { error?: { message?: string } })?.error?.message ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Types that match the FastAPI camelCase response format
// ---------------------------------------------------------------------------

export interface TaskLog {
  logId: number;
  taskId: number;
  category: string;
  message: string;
  extraData: unknown;
  createdAt: string;
}

export interface DevTask {
  id: number;
  title: string;
  description: string;
  status: string;
  plan: string | null;
  diff: string | null;
  filesTouched: string[];
  project: string | null;
  priority: string;
  assignedAgent: string | null;
  finalSummary: string | null;
  createdAt: string;
  updatedAt: string;
  logs: TaskLog[];
}

export interface PipelineStateClient {
  taskId: number;
  stage: string;
  pmBrief: unknown;
  architectPlan: unknown;
  subtasks: unknown;
  approved: boolean;
}

export interface ArtifactRecord {
  artifactId: string;
  taskId: string;
  artifactType: string;
  version: number;
  storagePath: string;
  createdByAgent: string;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Task CRUD
// ---------------------------------------------------------------------------

export async function fetchTasks(status?: string): Promise<DevTask[]> {
  const qs = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`/api/tasks${qs}`, { cache: "no-store" });
  const data = await handleResponse<{ tasks: DevTask[] }>(res);
  return data.tasks;
}

export async function fetchTask(taskId: string): Promise<DevTask> {
  const res = await fetch(`/api/tasks/${taskId}`, { cache: "no-store" });
  return handleResponse<DevTask>(res);
}

export async function createTask(input: { title: string; description: string }): Promise<DevTask> {
  const res = await fetch(`/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return handleResponse<DevTask>(res);
}

export async function updateTaskStatus(taskId: string, status: string): Promise<DevTask> {
  const res = await fetch(`/api/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return handleResponse<DevTask>(res);
}

// ---------------------------------------------------------------------------
// Planner agent (simple mode — POST /run with mode=simple)
// ---------------------------------------------------------------------------

export async function triggerAgentRun(taskId: string): Promise<{ triggered: boolean }> {
  const res = await fetch(`/api/tasks/${taskId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "simple" }),
  });
  return handleResponse(res);
}

// ---------------------------------------------------------------------------
// Planning pipeline (full mode — PM → Architect → Decomposer)
// ---------------------------------------------------------------------------

export async function triggerPipeline(taskId: string): Promise<{ triggered: boolean }> {
  const res = await fetch(`/api/tasks/${taskId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "full" }),
  });
  return handleResponse(res);
}

export async function fetchPipelineState(taskId: string): Promise<PipelineStateClient | null> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline`, { cache: "no-store" });
  if (res.status === 404) return null;
  return handleResponse<PipelineStateClient>(res);
}

// Approve the PM→Architect→Decomposer plan — resumes LangGraph + starts coder
export async function approvePipeline(taskId: string): Promise<{ approved: boolean }> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline/approve`, { method: "POST" });
  return handleResponse(res);
}

// Reject the plan — resumes LangGraph with approved=false
export async function rejectPipeline(taskId: string): Promise<{ rejected: boolean }> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline/reject`, { method: "POST" });
  return handleResponse(res);
}

// ---------------------------------------------------------------------------
// Artifacts (Phase 4)
// ---------------------------------------------------------------------------

export async function fetchArtifacts(taskId: string): Promise<ArtifactRecord[]> {
  const res = await fetch(`/api/tasks/${taskId}/artifacts`, { cache: "no-store" });
  if (!res.ok) return [];
  return handleResponse<ArtifactRecord[]>(res);
}
