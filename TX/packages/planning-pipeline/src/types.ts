import { z } from "zod";

export const PmBriefSchema = z.object({
  goals: z.array(z.string()),
  constraints: z.array(z.string()),
  acceptanceCriteria: z.array(z.string()),
  riskAreas: z.array(z.string()),
  estimatedComplexity: z.enum(["low", "medium", "high"]),
});
export type PmBrief = z.infer<typeof PmBriefSchema>;

export const ArchitectPlanSchema = z.object({
  technicalApproach: z.string(),
  impactedSystems: z.array(z.string()),
  impactedFiles: z.array(z.string()),
  risks: z.array(z.string()),
  testingStrategy: z.string(),
  implementationNotes: z.string(),
});
export type ArchitectPlan = z.infer<typeof ArchitectPlanSchema>;

export const SubTaskTypeSchema = z.enum(["backend", "frontend", "test", "docs", "config", "migration"]);
export type SubTaskType = z.infer<typeof SubTaskTypeSchema>;

export const SubTaskSchema = z.object({
  id: z.string(),
  type: SubTaskTypeSchema,
  title: z.string(),
  description: z.string(),
  filesToEdit: z.array(z.string()),
  dependsOn: z.array(z.string()),
});
export type SubTask = z.infer<typeof SubTaskSchema>;

export const PipelineStageSchema = z.enum([
  "pm_agent",
  "architect_agent",
  "task_decomposer",
  "awaiting_approval",
  "approved",
  "rejected",
  "error",
]);
export type PipelineStage = z.infer<typeof PipelineStageSchema>;

export const PipelineStateSchema = z.object({
  id: z.string(),
  taskId: z.string(),
  stage: PipelineStageSchema,
  pmBrief: PmBriefSchema.nullable(),
  architectPlan: ArchitectPlanSchema.nullable(),
  subtasks: z.array(SubTaskSchema).nullable(),
  error: z.string().nullable(),
  createdAt: z.date(),
  updatedAt: z.date(),
});
export type PipelineState = z.infer<typeof PipelineStateSchema>;
