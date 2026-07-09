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

// ---------------------------------------------------------------------------
// Epics (Phase 5)
// ---------------------------------------------------------------------------

export interface EpicTask {
  taskId: number;
  title: string;
  status: string;
  createdAt: string;
}

export interface Epic {
  epicId: string;
  title: string;
  description: string;
  status: string;
  costEstimate: number | null;
  costActual: number | null;
  haltReason: string | null;
  createdAt: string;
  updatedAt?: string;
  tasks?: EpicTask[];
}

export async function fetchEpics(): Promise<Epic[]> {
  const res = await fetch("/api/epics", { cache: "no-store" });
  if (!res.ok) return [];
  return handleResponse<Epic[]>(res);
}

export async function fetchEpic(epicId: string): Promise<Epic> {
  const res = await fetch(`/api/epics/${epicId}`, { cache: "no-store" });
  return handleResponse<Epic>(res);
}

export async function createEpic(input: {
  title: string;
  description: string;
  complexityMultiplier?: number;
}): Promise<{ epicId: string; status: string; costEstimate: number; requiresCostApproval: boolean }> {
  const res = await fetch("/api/epics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      description: input.description,
      complexity_multiplier: input.complexityMultiplier ?? 1.0,
    }),
  });
  return handleResponse(res);
}

export async function approveEpic(
  epicId: string,
  userId: string,
): Promise<{ epicId: string; status: string }> {
  const res = await fetch(`/api/epics/${epicId}/approve`, {
    method: "POST",
    headers: { "X-User-Id": userId },
  });
  return handleResponse(res);
}

export async function rejectEpic(
  epicId: string,
  userId: string,
): Promise<{ epicId: string; status: string }> {
  const res = await fetch(`/api/epics/${epicId}/reject`, {
    method: "POST",
    headers: { "X-User-Id": userId },
  });
  return handleResponse(res);
}

export async function approveCost(
  epicId: string,
  userId: string,
): Promise<{ epicId: string; status: string }> {
  const res = await fetch(`/api/epics/${epicId}/approve-cost`, {
    method: "POST",
    headers: { "X-User-Id": userId },
  });
  return handleResponse(res);
}

// ---------------------------------------------------------------------------
// Goals (Phase 7) — plain-language goals → epics via Executive Agent
// ---------------------------------------------------------------------------

export interface Goal {
  goalId: string;
  text: string;
  status: string;
  epicIds: string[];
  summary: string | null;
}

export async function fetchGoals(): Promise<Goal[]> {
  const res = await fetch("/api/goals", { cache: "no-store" });
  if (!res.ok) return [];
  return handleResponse<Goal[]>(res);
}

export async function fetchGoal(goalId: string): Promise<Goal> {
  const res = await fetch(`/api/goals/${goalId}`, { cache: "no-store" });
  return handleResponse<Goal>(res);
}

export async function createGoal(text: string): Promise<Goal> {
  const res = await fetch("/api/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return handleResponse<Goal>(res);
}

// ---------------------------------------------------------------------------
// Metrics (Phase 7) — productivity dashboard
// ---------------------------------------------------------------------------

export interface AgentTypeSummary {
  agentType: string;
  runCount: number;
  totalTokensIn: number;
  totalTokensOut: number;
  totalCacheReadTokens: number;
  totalCacheCreationTokens: number;
  cacheHitRate: number;
}

export interface SystemMetrics {
  totalEpics: number;
  epicsByStatus: Record<string, number>;
  totalAgentRuns: number;
  totalTokensIn: number;
  totalTokensOut: number;
  totalCacheReadTokens: number;
  totalCacheCreationTokens: number;
  cacheHitRate: number;
  agentTypeBreakdown: AgentTypeSummary[];
}

export interface EpicCostSummary {
  epicId: string;
  title: string;
  status: string;
  tokensIn: number;
  tokensOut: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  cacheHitRate: number;
  costEstimate: number | null;
  costActual: number | null;
}

export async function fetchSystemMetrics(): Promise<SystemMetrics> {
  const res = await fetch("/api/metrics", { cache: "no-store" });
  return handleResponse<SystemMetrics>(res);
}

export async function fetchEpicCosts(): Promise<EpicCostSummary[]> {
  const res = await fetch("/api/metrics/epics", { cache: "no-store" });
  if (!res.ok) return [];
  return handleResponse<EpicCostSummary[]>(res);
}
