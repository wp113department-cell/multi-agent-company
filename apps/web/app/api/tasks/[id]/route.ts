import { UpdateTaskInput } from "@gridiron/shared-types";
import { getTask, InvalidTransitionError, listTaskLogs, updateTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";

// GET /tasks/:id — task record plus its full log timeline (08_API_Specification.md)
export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }
  const logs = await listTaskLogs(params.id);
  return NextResponse.json({ ...task, logs });
}

// PATCH /tasks/:id — update task fields (status, assignedAgent, etc.)
export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json().catch(() => null);
  const parsed = UpdateTaskInput.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_error", message: parsed.error.message } },
      { status: 400 },
    );
  }

  try {
    const task = await updateTask(params.id, parsed.data);
    return NextResponse.json(task);
  } catch (err) {
    if (err instanceof InvalidTransitionError) {
      return NextResponse.json(
        { error: { code: "conflict", message: err.message } },
        { status: 409 },
      );
    }
    if (err instanceof Error && err.message.startsWith("Task not found")) {
      return NextResponse.json(
        { error: { code: "not_found", message: err.message } },
        { status: 404 },
      );
    }
    throw err;
  }
}
