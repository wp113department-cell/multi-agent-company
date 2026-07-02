import { z } from "zod";

/**
 * Status lifecycle. Base set is from 09_Database_Design_Specification.md's
 * `dev_tasks.status` CHECK constraint. Two states are added here because the
 * spec's own definition-of-done table (04_Engineering_Standards_Conventions.md)
 * and API spec (08_API_Specification.md, /tasks/:id/reject) require them:
 * `ready_for_review` (plan/patch awaiting human approval) and `rejected`
 * (human rejected a proposed patch, agent may be re-triggered).
 */
export const TaskStatus = z.enum([
  "pending",
  "planning",
  "ready_for_review",
  "coding",
  "testing",
  "blocked",
  "completed",
  "failed",
  "rejected",
]);
export type TaskStatus = z.infer<typeof TaskStatus>;

export const TaskPriority = z.enum(["low", "medium", "high"]);
export type TaskPriority = z.infer<typeof TaskPriority>;

export const DevTask = z.object({
  taskId: z.string().uuid(),
  title: z.string().min(1),
  description: z.string().nullable(),
  priority: TaskPriority,
  status: TaskStatus,
  assignedAgent: z.string().nullable(),
  project: z.string().nullable(),
  filesTouched: z.array(z.string()).default([]),
  plan: z.string().nullable(),
  diff: z.string().nullable(),
  finalSummary: z.string().nullable(),
  createdAt: z.coerce.date(),
  updatedAt: z.coerce.date(),
});
export type DevTask = z.infer<typeof DevTask>;

/** Body accepted by POST /tasks (08_API_Specification.md). */
export const CreateTaskInput = z.object({
  title: z.string().min(1),
  description: z.string().optional(),
  priority: TaskPriority.default("medium"),
  project: z.string().optional(),
});
export type CreateTaskInput = z.infer<typeof CreateTaskInput>;

/** Body accepted by PATCH /tasks/:id. */
export const UpdateTaskInput = z.object({
  status: TaskStatus.optional(),
  assignedAgent: z.string().nullable().optional(),
  filesTouched: z.array(z.string()).optional(),
  plan: z.string().nullable().optional(),
  diff: z.string().nullable().optional(),
  finalSummary: z.string().nullable().optional(),
});
export type UpdateTaskInput = z.infer<typeof UpdateTaskInput>;
