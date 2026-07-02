import { getTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";
import path from "path";

// POST /api/tasks/:id/pipeline/approve — human approves the pipeline plan, starts coding agent
export async function POST(_req: NextRequest, { params }: { params: { id: string } }) {
  const { getPipelineState, updatePipelineState } = await import("@gridiron/planning-pipeline");

  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }

  const pipelineState = await getPipelineState(params.id);
  if (!pipelineState || pipelineState.stage !== "awaiting_approval") {
    return NextResponse.json(
      {
        error: {
          code: "conflict",
          message: `Pipeline not awaiting approval (stage: ${pipelineState?.stage ?? "none"})`,
        },
      },
      { status: 409 },
    );
  }

  // Mark pipeline as approved and kick off the coding agent
  await updatePipelineState(params.id, { stage: "approved" });

  const repoPath = path.resolve(process.env["TARGET_REPO_PATH"] ?? process.cwd() + "/../../");
  const taskId = params.id;

  setImmediate(() => {
    import("@gridiron/agent-runtime")
      .then(({ runTaskAgent }) => runTaskAgent(taskId, repoPath))
      .catch((err: unknown) => {
        console.error(`[agent-runtime] Task ${taskId} coding failed:`, err);
      });
  });

  return NextResponse.json({ message: "Pipeline approved, coding agent started", taskId });
}
