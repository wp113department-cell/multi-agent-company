import { getTask } from "@gridiron/task-engine";
import { runCodingAgent } from "./coding-agent";
import { runPlannerAgent } from "./planner-agent";
import type { AgentContext } from "./types";

export async function runTaskAgent(taskId: string, repoPath: string): Promise<void> {
  const task = await getTask(taskId);
  if (!task) throw new Error(`Task not found: ${taskId}`);

  const ctx: AgentContext = { taskId, repoPath };

  switch (task.status) {
    case "pending":
    case "rejected":
      await runPlannerAgent(ctx);
      break;

    case "ready_for_review":
      if (task.plan && !task.diff) {
        // Plan exists, no diff yet — run the coding agent
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
