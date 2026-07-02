import { z } from "zod";

/**
 * Category set per 09_Database_Design_Specification.md's task_logs comment,
 * extended with categories the Stage 2-lite patch/policy flow needs
 * (denied, patch_proposed, retry) since the spec only enumerates Stage 1
 * categories explicitly.
 */
export const TaskLogCategory = z.enum([
  "created",
  "planning",
  "repo_analysis",
  "files_inspected",
  "patch_proposed",
  "policy_denied",
  "retry",
  "error",
  "warning",
  "summary",
]);
export type TaskLogCategory = z.infer<typeof TaskLogCategory>;

export const TaskLog = z.object({
  logId: z.string().uuid(),
  taskId: z.string().uuid(),
  category: TaskLogCategory,
  message: z.string(),
  metadata: z.record(z.unknown()).nullable(),
  createdAt: z.coerce.date(),
});
export type TaskLog = z.infer<typeof TaskLog>;

/** Body accepted by POST /tasks/:id/logs. */
export const CreateTaskLogInput = z.object({
  category: TaskLogCategory,
  message: z.string().min(1),
  metadata: z.record(z.unknown()).optional(),
});
export type CreateTaskLogInput = z.infer<typeof CreateTaskLogInput>;
