import { getTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";
import path from "path";

// POST /api/tasks/:id/run — trigger a planner or coding agent run.
// Returns 202 immediately; the agent updates the DB in the background.
// The dashboard polls /api/tasks/:id every 3 s to show live progress.
export async function POST(_req: NextRequest, { params }: { params: { id: string } }) {
  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }

  const runnable = ["pending", "rejected", "ready_for_review"].includes(task.status);
  if (!runnable) {
    return NextResponse.json(
      {
        error: {
          code: "conflict",
          message: `Cannot run agent for task in status "${task.status}". Expected: pending, rejected, or ready_for_review.`,
        },
      },
      { status: 409 },
    );
  }

  // Resolve repo path — defaults to this monorepo root when not configured
  const repoPath = path.resolve(process.env["TARGET_REPO_PATH"] ?? process.cwd() + "/../../");

  const taskId = params.id;

  // Fire-and-forget: agent writes progress to DB; UI polls for updates
  setImmediate(() => {
    import("@gridiron/agent-runtime")
      .then(({ runTaskAgent }) => runTaskAgent(taskId, repoPath))
      .catch((err: unknown) => {
        console.error(`[agent-runtime] Task ${taskId} failed:`, err);
      });
  });

  return NextResponse.json(
    { message: "Agent run started", taskId, status: task.status },
    { status: 202 },
  );
}
