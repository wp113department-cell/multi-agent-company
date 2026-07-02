import { getTask } from "@gridiron/task-engine";
import { getConfig } from "@gridiron/shared-config";
import { runCodingAgent } from "./coding-agent";
import { runPlannerAgent } from "./planner-agent";
import type { AgentContext } from "./types";

export async function runTaskAgent(taskId: string, repoPath: string): Promise<void> {
  const task = await getTask(taskId);
  if (!task) throw new Error(`Task not found: ${taskId}`);

  const ctx: AgentContext = { taskId, repoPath };
  const pipelineMode = getConfig().PIPELINE_MODE;

  switch (task.status) {
    case "pending":
    case "rejected":
      if (pipelineMode === "simple") {
        // simple mode: skip planning pipeline, go straight to coding
        await runCodingAgent(ctx);
      } else {
        // full mode: planner agent produces a markdown plan first
        await runPlannerAgent(ctx);
      }
      break;

    case "ready_for_review":
      if (task.plan && !task.diff) {
        await runCodingAgent(ctx);
      } else {
        throw new Error(`Task ${taskId} is in ready_for_review but coding cannot start: no plan or diff already exists`);
      }
      break;

    default:
      throw new Error(
        `Cannot start agent for task ${taskId} in status "${task.status}". ` +
        `Expected: pending, rejected, or ready_for_review (with plan but no diff).`,
      );
  }
}
