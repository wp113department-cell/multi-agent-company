import path from "path";
import { buildContext } from "@gridiron/context-builder";
import { getTask, appendTaskLog } from "@gridiron/task-engine";
import { runPmAgent } from "./pm-agent";
import { runArchitectAgent } from "./architect-agent";
import { runDecomposer } from "./decomposer";
import { createPipelineState, getPipelineState, updatePipelineState } from "./state-store";
import type { PipelineState } from "./types";

export async function runPlanningPipeline(
  taskId: string,
  repoPath: string,
): Promise<PipelineState> {
  const task = await getTask(taskId);
  if (!task) throw new Error(`Task not found: ${taskId}`);

  const absRepo = path.resolve(repoPath);

  await createPipelineState(taskId);

  // ── Resume detection: check what stages already completed ─────────────────
  const existing = await getPipelineState(taskId);
  const hasPmBrief = !!existing?.pmBrief;
  const hasArchitectPlan = !!existing?.architectPlan;
  const hasSubtasks = !!existing?.subtasks;

  if (hasSubtasks) {
    // All stages done — skip straight to human approval
    await appendTaskLog(taskId, {
      category: "planning",
      message: "Resuming pipeline: all stages complete, moving to awaiting approval",
      metadata: {},
    });
    return await updatePipelineState(taskId, { stage: "awaiting_approval" });
  }

  await appendTaskLog(taskId, {
    category: "planning",
    message: hasPmBrief
      ? "Resuming pipeline from Architect Agent (PM brief already exists)"
      : hasArchitectPlan
        ? "Resuming pipeline from Task Decomposer (architect plan already exists)"
        : "Planning pipeline started (PM Agent → Architect Agent → Task Decomposer)",
    metadata: {},
  });

  try {
    // ── Stage 1: PM Agent (skip if already done) ────────────────────────────
    let pmBrief = existing?.pmBrief ?? null;
    if (!hasPmBrief) {
      await updatePipelineState(taskId, { stage: "pm_agent" });
      await appendTaskLog(taskId, {
        category: "planning",
        message: "PM Agent: building product brief…",
        metadata: {},
      });

      const context = await buildContext(task, absRepo);
      pmBrief = await runPmAgent(task, context);

      await updatePipelineState(taskId, { pmBrief });
      await appendTaskLog(taskId, {
        category: "planning",
        message: `PM Agent: brief complete. Complexity: ${pmBrief.estimatedComplexity}. Goals: ${pmBrief.goals.length}`,
        metadata: { pmBrief },
      });
    }

    // ── Stage 2: Architect Agent (skip if already done) ─────────────────────
    let architectPlan = existing?.architectPlan ?? null;
    if (!hasArchitectPlan) {
      await updatePipelineState(taskId, { stage: "architect_agent" });
      await appendTaskLog(taskId, {
        category: "planning",
        message: "Architect Agent: designing technical approach…",
        metadata: {},
      });

      const context = await buildContext(task, absRepo);
      architectPlan = await runArchitectAgent(task, pmBrief!, context);

      await updatePipelineState(taskId, { architectPlan });
      await appendTaskLog(taskId, {
        category: "planning",
        message: `Architect Agent: plan complete. Impacted files: ${architectPlan.impactedFiles.length}`,
        metadata: { architectPlan },
      });
    }

    // ── Stage 3: Task Decomposer ────────────────────────────────────────────
    await updatePipelineState(taskId, { stage: "task_decomposer" });
    await appendTaskLog(taskId, {
      category: "planning",
      message: "Task Decomposer: breaking into subtasks…",
      metadata: {},
    });

    const subtasks = await runDecomposer(pmBrief!, architectPlan!);

    await updatePipelineState(taskId, { subtasks });
    await appendTaskLog(taskId, {
      category: "planning",
      message: `Task Decomposer: ${subtasks.length} subtask(s) identified`,
      metadata: { subtaskTitles: subtasks.map((s) => s.title) },
    });

    // ── Human-in-the-loop interrupt ─────────────────────────────────────────
    const finalState = await updatePipelineState(taskId, { stage: "awaiting_approval" });
    await appendTaskLog(taskId, {
      category: "patch_proposed",
      message: "Planning pipeline complete. Awaiting human approval before coding begins.",
      metadata: { subtaskCount: subtasks.length },
    });

    return finalState;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await updatePipelineState(taskId, { stage: "error", error: msg });
    await appendTaskLog(taskId, {
      category: "error",
      message: `Planning pipeline error: ${msg}`,
      metadata: { error: msg },
    });
    throw err;
  }
}

export { getPipelineState } from "./state-store";
