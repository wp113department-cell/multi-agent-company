import { CreateTaskInput, TaskStatus } from "@gridiron/shared-types";
import { appendTaskLog, createTask, listTasks } from "@gridiron/task-engine";
import { NextRequest, NextResponse } from "next/server";

// POST /tasks — create a new development task (08_API_Specification.md)
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = CreateTaskInput.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_error", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const task = await createTask(parsed.data);
  await appendTaskLog(task.taskId, {
    category: "created",
    message: `Task created: "${task.title}"`,
  });

  return NextResponse.json(task, { status: 201 });
}

// GET /tasks?status=&project=&cursor=&limit= — list tasks, cursor-paginated
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const statusParam = searchParams.get("status");
  const status = statusParam ? TaskStatus.safeParse(statusParam) : undefined;
  if (status && !status.success) {
    return NextResponse.json(
      { error: { code: "validation_error", message: `Invalid status: ${statusParam}` } },
      { status: 400 },
    );
  }
  const project = searchParams.get("project") ?? undefined;
  const cursor = searchParams.get("cursor") ?? undefined;
  const limitParam = searchParams.get("limit");

  const limit = limitParam ? Number(limitParam) : 20;
  const tasks = await listTasks({
    status: status?.data,
    project,
    cursor,
    limit,
  });

  const nextCursor = tasks.length === limit ? tasks[tasks.length - 1]?.taskId : null;
  return NextResponse.json({ tasks, nextCursor });
}
