import { NextRequest, NextResponse } from "next/server";
import { getTask, updateTask, appendTaskLog } from "@gridiron/task-engine";

// POST /api/tasks/:id/reject — reject a task in ready_for_review, mark as rejected
export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
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
          message: `Task cannot be rejected in status "${task.status}". Expected: ready_for_review.`,
        },
      },
      { status: 409 },
    );
  }

  const body = await req.json().catch(() => ({}));
  const reason = typeof body?.reason === "string" ? body.reason : "Rejected by human reviewer";

  await updateTask(params.id, { status: "rejected" });
  await appendTaskLog(params.id, {
    category: "warning",
    message: `Task rejected: ${reason}`,
    metadata: { reason },
  });

  return NextResponse.json({ message: "Task rejected", taskId: params.id, reason });
}
