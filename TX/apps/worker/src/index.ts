import path from "path";
import { runTaskAgent } from "@gridiron/agent-runtime";
import { listTasks } from "@gridiron/task-engine";

const POLL_INTERVAL_MS = 10_000;
const WEEKLY_MS = 7 * 24 * 60 * 60 * 1000;
const REPO_PATH = path.resolve(process.env["TARGET_REPO_PATH"] ?? process.cwd() + "/../../");
const MAX_CONCURRENT = 1;

let running = 0;
let lastReindexAt = 0;

async function pickupPendingTask(): Promise<void> {
  if (running >= MAX_CONCURRENT) return;

  const tasks = await listTasks({ status: "pending", limit: 1 });
  const task = tasks[0];
  if (!task) return;

  running++;
  console.log(`[worker] Picked up task ${task.taskId}: "${task.title}" — running planner agent`);

  try {
    await runTaskAgent(task.taskId, REPO_PATH);
    console.log(`[worker] Task ${task.taskId} planner finished`);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[worker] Task ${task.taskId} failed: ${msg}`);
  } finally {
    running--;
  }
}

async function weeklyReindex(): Promise<void> {
  if (Date.now() - lastReindexAt < WEEKLY_MS) return;
  lastReindexAt = Date.now();
  console.log("[worker] Weekly reindex triggered");
  try {
    const { indexRepository, generateEmbeddings } = await import("@gridiron/repo-intelligence");
    const { invalidateContextCache } = await import("@gridiron/context-builder");
    const { getPool } = await import("@gridiron/shared-db");
    invalidateContextCache(REPO_PATH);
    const index = await indexRepository(REPO_PATH);
    console.log(`[worker] Reindex: ${index.files.length} files, ${index.symbols.length} symbols`);
    await generateEmbeddings(index, getPool());
    console.log("[worker] Embedding refresh complete");
  } catch (err) {
    console.error("[worker] Reindex error:", err instanceof Error ? err.message : err);
  }
}

async function poll(): Promise<void> {
  try {
    await weeklyReindex();
    await pickupPendingTask();
  } catch (err) {
    console.error("[worker] Poll error:", err);
  }
}

console.log(`[worker] Starting. REPO_PATH=${REPO_PATH} POLL=${POLL_INTERVAL_MS}ms`);
void poll();
setInterval(() => void poll(), POLL_INTERVAL_MS);
