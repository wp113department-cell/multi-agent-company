/**
 * Task Queue integration tests — exercise task CRUD, status transitions,
 * and log appending logic. Uses real DB if DATABASE_URL is set; skips otherwise.
 *
 * Run: DATABASE_URL=<test-db-url> pnpm test tests/integration/task-queue.test.ts
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";

const DB_URL = process.env["DATABASE_URL"];
const SKIP = !DB_URL;

describe.skipIf(SKIP)("Task Queue — DB integration", () => {
  let createdTaskId: string;

  beforeAll(async () => {
    if (SKIP) return;
    const { createPool } = await import("@gridiron/shared-db");
    await createPool(DB_URL!);
  });

  afterAll(async () => {
    if (SKIP || !createdTaskId) return;
    const { query } = await import("@gridiron/shared-db");
    await query("DELETE FROM dev_tasks WHERE task_id = $1", [createdTaskId]);
  });

  it("creates a task and reads it back", async () => {
    const { createTask, getTask } = await import("@gridiron/task-engine");
    const task = await createTask({
      title: "Integration test task",
      description: "Created by integration test",
      priority: "low",
    });
    createdTaskId = task.taskId;

    expect(task.taskId).toBeDefined();
    expect(task.status).toBe("pending");
    expect(task.title).toBe("Integration test task");

    const fetched = await getTask(task.taskId);
    expect(fetched?.taskId).toBe(task.taskId);
    expect(fetched?.priority).toBe("low");
  });

  it("updates task status with valid transition", async () => {
    const { updateTask, getTask } = await import("@gridiron/task-engine");
    await updateTask(createdTaskId, { status: "planning" });
    const task = await getTask(createdTaskId);
    expect(task?.status).toBe("planning");
  });

  it("rejects invalid status transition", async () => {
    const { updateTask } = await import("@gridiron/task-engine");
    await expect(updateTask(createdTaskId, { status: "done" })).rejects.toThrow();
  });

  it("appends and lists task logs", async () => {
    const { appendTaskLog, listTaskLogs } = await import("@gridiron/task-engine");
    await appendTaskLog(createdTaskId, {
      category: "planning",
      message: "Integration test log entry",
      metadata: { test: true },
    });
    const logs = await listTaskLogs(createdTaskId);
    expect(logs.length).toBeGreaterThan(0);
    const logEntry = logs.find((l) => l.message === "Integration test log entry");
    expect(logEntry).toBeDefined();
    expect(logEntry?.metadata?.test).toBe(true);
  });

  it("lists tasks with cursor pagination", async () => {
    const { listTasks } = await import("@gridiron/task-engine");
    const page1 = await listTasks({ limit: 1 });
    expect(page1.length).toBeLessThanOrEqual(1);
  });
});

describe("Task Queue — unit (no DB)", () => {
  it("status transitions module rejects impossible transitions", async () => {
    const { assertValidTransition } = await import("@gridiron/task-engine");
    expect(() => assertValidTransition("pending", "done")).toThrow();
    expect(() => assertValidTransition("done", "pending")).toThrow();
  });

  it("status transitions module allows valid paths", async () => {
    const { assertValidTransition } = await import("@gridiron/task-engine");
    expect(() => assertValidTransition("pending", "planning")).not.toThrow();
    expect(() => assertValidTransition("planning", "ready_for_review")).not.toThrow();
    expect(() => assertValidTransition("ready_for_review", "coding")).not.toThrow();
    expect(() => assertValidTransition("coding", "testing")).not.toThrow();
    expect(() => assertValidTransition("testing", "ready_for_review")).not.toThrow();
    expect(() => assertValidTransition("ready_for_review", "completed")).not.toThrow();
  });
});
