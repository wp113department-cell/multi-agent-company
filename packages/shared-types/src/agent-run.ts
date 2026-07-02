import { z } from "zod";

/** Per 06_Agent_SDK_Specification.md's Agent Lifecycle. */
export const AgentRunStatus = z.enum([
  "created",
  "planning",
  "coding",
  "testing",
  "blocked",
  "completed",
  "failed",
]);
export type AgentRunStatus = z.infer<typeof AgentRunStatus>;

export const AgentRun = z.object({
  runId: z.string().uuid(),
  taskId: z.string().uuid(),
  agentType: z.string(),
  modelId: z.string().nullable(),
  status: AgentRunStatus,
  checkpointId: z.string().nullable(),
  tokensIn: z.number().int().nullable(),
  tokensOut: z.number().int().nullable(),
  costEstimate: z.number().nullable(),
  lastHeartbeatAt: z.coerce.date().nullable(),
  startedAt: z.coerce.date(),
  completedAt: z.coerce.date().nullable(),
});
export type AgentRun = z.infer<typeof AgentRun>;
