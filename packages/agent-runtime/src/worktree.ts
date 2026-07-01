import { exec, execFile } from "child_process";
import fs from "fs/promises";
import os from "os";
import path from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export function worktreePath(taskId: string): string {
  return path.join(os.tmpdir(), "gridiron", `task-${taskId}`);
}

export function worktreeBranch(taskId: string): string {
  return `gridiron/task-${taskId}`;
}

export async function createWorktree(repoPath: string, taskId: string): Promise<string> {
  const wPath = worktreePath(taskId);
  const branch = worktreeBranch(taskId);

  await fs.mkdir(path.dirname(wPath), { recursive: true });

  // Remove stale worktree + branch from previous runs
  try {
    await execFileAsync("git", ["worktree", "remove", "--force", wPath], { cwd: repoPath });
  } catch { /* fine */ }
  try {
    await execFileAsync("git", ["branch", "-D", branch], { cwd: repoPath });
  } catch { /* fine */ }

  await execFileAsync("git", ["worktree", "add", "-b", branch, wPath], { cwd: repoPath });

  // Symlink root node_modules so pnpm/typecheck work without re-install
  const srcModules = path.join(repoPath, "node_modules");
  const dstModules = path.join(wPath, "node_modules");
  try {
    await fs.symlink(srcModules, dstModules);
  } catch { /* already exists or not applicable */ }

  return wPath;
}

export async function commitWorktreeChanges(worktreePath: string, message: string): Promise<void> {
  try {
    await execFileAsync("git", ["add", "-A"], { cwd: worktreePath });
    await execFileAsync(
      "git",
      ["-c", "user.email=agent@gridiron.ai", "-c", "user.name=Gridiron Agent",
       "commit", "--allow-empty", "-m", message],
      { cwd: worktreePath },
    );
  } catch {
    // No changes to commit — that's fine
  }
}

export async function removeWorktree(repoPath: string, taskId: string): Promise<void> {
  const wPath = worktreePath(taskId);
  const branch = worktreeBranch(taskId);
  try {
    await execFileAsync("git", ["worktree", "remove", "--force", wPath], { cwd: repoPath });
  } catch { /* best-effort */ }
  try {
    await execFileAsync("git", ["branch", "-D", branch], { cwd: repoPath });
  } catch { /* best-effort */ }
}

export async function getWorktreeDiff(repoPath: string, taskId: string): Promise<string> {
  const branch = worktreeBranch(taskId);
  try {
    const { stdout } = await execFileAsync("git", ["diff", `HEAD..${branch}`], {
      cwd: repoPath,
      maxBuffer: 4 * 1024 * 1024,
    });
    return stdout.trim() || "(no file changes from coding agent)";
  } catch (err) {
    return `(diff error: ${err instanceof Error ? err.message : String(err)})`;
  }
}

export async function runTypecheckInWorktree(worktreePath: string): Promise<{ passed: boolean; output: string }> {
  return new Promise((resolve) => {
    exec(
      "pnpm turbo run typecheck 2>&1",
      { cwd: worktreePath, timeout: 120_000, maxBuffer: 1024 * 1024 },
      (_err, stdout, stderr) => {
        const output = [stdout, stderr].filter(Boolean).join("\n").trim();
        const passed = !output.includes("error TS") && !output.includes("ELIFECYCLE");
        resolve({ passed, output: output.slice(0, 4000) });
      },
    );
  });
}
