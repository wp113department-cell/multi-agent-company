import { getTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";
import path from "path";

// GET /api/tasks/:id/pipeline — return current pipeline state
export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const { getPipelineState } = await import("@gridiron/planning-pipeline");
  const state = await getPipelineState(params.id);
  if (!state) {
    return NextResponse.json(
      { error: { code: "not_found", message: "No pipeline state for this task" } },
      { status: 404 },
    );
  }
  return NextResponse.json(state);
}

// POST /api/tasks/:id/pipeline — trigger the planning pipeline (PM → Architect → Decomposer)
export async function POST(_req: NextRequest, { params }: { params: { id: string } }) {
  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }

  const repoPath = path.resolve(process.env["TARGET_REPO_PATH"] ?? process.cwd() + "/../../");
  const taskId = params.id;

  // Fire-and-forget: pipeline runs in background, dashboard polls for updates
  setImmediate(() => {
    import("@gridiron/planning-pipeline")
      .then(({ runPlanningPipeline }) => runPlanningPipeline(taskId, repoPath))
      .catch((err: unknown) => {
        console.error(`[planning-pipeline] Task ${taskId} failed:`, err);
      });
  });

  return NextResponse.json(
    { message: "Planning pipeline started", taskId },
    { status: 202 },
  );
}
