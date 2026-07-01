import { getTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";

// GET /api/tasks/:id/diff — returns the raw diff stored on the task
export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }
  if (!task.diff) {
    return NextResponse.json(
      { error: { code: "not_found", message: "No diff available for this task" } },
      { status: 404 },
    );
  }
  return new NextResponse(task.diff, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
