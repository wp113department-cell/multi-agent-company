import { CreateTaskLogInput } from "@gridiron/shared-types";
import { appendTaskLog, getTask } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";

// POST /tasks/:id/logs — append a log entry (08_API_Specification.md)
export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  const task = await getTask(params.id);
  if (!task) {
    return NextResponse.json(
      { error: { code: "not_found", message: `Task not found: ${params.id}` } },
      { status: 404 },
    );
  }

  const body = await req.json().catch(() => null);
  const parsed = CreateTaskLogInput.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_error", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const log = await appendTaskLog(params.id, parsed.data);
  return NextResponse.json(log, { status: 201 });
}
