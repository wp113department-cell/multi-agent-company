/**
 * Worktree lifecycle tests — verify that:
 * 1. createWorktree() creates an isolated git branch
 * 2. Files written in the worktree don't appear in the main repo
 * 3. removeWorktree() cleans up
 *
 * Requires: git executable, and runs in a temp bare repo
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { exec } from "child_process";
import { promisify } from "util";
import fs from "fs/promises";
import os from "os";
import path from "path";

const execAsync = promisify(exec);

// shared-config requires DATABASE_URL even for non-DB code paths; set a dummy value
if (!process.env["DATABASE_URL"]) {
  process.env["DATABASE_URL"] = "postgresql://gridiron:gridiron_dev_only@localhost:5432/gridiron_test";
}

describe("Worktree lifecycle", () => {
  let tempRepoDir: string;
  let worktreeDir: string;

  beforeAll(async () => {
    // Create a temp git repo as our test "main repo"
    tempRepoDir = await fs.mkdtemp(path.join(os.tmpdir(), "gridiron-test-repo-"));
    await execAsync("git init", { cwd: tempRepoDir });
    await execAsync('git config user.email "test@test.com"', { cwd: tempRepoDir });
    await execAsync('git config user.name "Test"', { cwd: tempRepoDir });
    await fs.writeFile(path.join(tempRepoDir, "README.md"), "# Test repo");
    await execAsync("git add . && git commit -m 'initial'", { cwd: tempRepoDir });
  });

  afterAll(async () => {
    await fs.rm(tempRepoDir, { recursive: true, force: true });
    if (worktreeDir) {
      await fs.rm(worktreeDir, { recursive: true, force: true }).catch(() => {});
    }
  });

  it("creates a worktree in an isolated branch", async () => {
    const { createWorktree } = await import("@gridiron/agent-runtime");
    worktreeDir = await createWorktree(tempRepoDir, "test-task-001");

    const stat = await fs.stat(worktreeDir);
    expect(stat.isDirectory()).toBe(true);

    const { stdout: branches } = await execAsync("git branch", { cwd: tempRepoDir });
    expect(branches).toContain("task-test-task-001");
  });

  it("writes in worktree do not appear in main repo", async () => {
    const testFile = path.join(worktreeDir, "agent-output.ts");
    await fs.writeFile(testFile, "export const x = 1;");

    const mainFile = path.join(tempRepoDir, "agent-output.ts");
    await expect(fs.stat(mainFile)).rejects.toThrow();
  });

  it("removes worktree cleanly", async () => {
    const { removeWorktree } = await import("@gridiron/agent-runtime");
    await removeWorktree(tempRepoDir, "test-task-001");

    await expect(fs.stat(worktreeDir)).rejects.toThrow();
  });
});
