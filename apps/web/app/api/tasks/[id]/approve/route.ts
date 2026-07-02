import { appendTaskLog, getTask, updateTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";
import path from "path";

// POST /api/tasks/:id/approve — approve a task in ready_for_review, start coding agent
export async function POST(_req: NextRequest, { params }: { params: { id: string } }) {
  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }

  if (task.status !== "ready_for_review") {
    return NextResponse.json(
      {
        error: {
          code: "conflict",
          message: `Task cannot be approved in status "${task.status}". Expected: ready_for_review.`,
        },
      },
      { status: 409 },
    );
  }

  await appendTaskLog(params.id, {
    category: "planning",
    message: "Task approved by human — coding agent will start",
    metadata: {},
  });

  const repoPath = path.resolve(process.env["TARGET_REPO_PATH"] ?? process.cwd() + "/../../");
  const taskId = params.id;

  setImmediate(() => {
    import("@gridiron/agent-runtime")
      .then(({ runCodingAgent }) => runCodingAgent({ taskId, repoPath }))
      .catch((err: unknown) => {
        console.error(`[agent-runtime] Coding agent for task ${taskId} failed:`, err);
      });
  });

  return NextResponse.json({ message: "Task approved — coding agent started", taskId }, { status: 202 });
}
