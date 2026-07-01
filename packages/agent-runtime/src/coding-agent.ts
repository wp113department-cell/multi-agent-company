import { exec } from "child_process";
import fs from "fs/promises";
import path from "path";
import { appendTaskLog, getTask, updateTask } from "@gridiron/task-engine";
import { listFiles, readFile } from "@gridiron/repo-tools";
import { checkCommand, checkPath } from "@gridiron/policy-engine";
import { runAgentLoop } from "./base-agent";
import { AgentDoneSignal, type AgentContext, type AgentTool } from "./types";
import {
  commitWorktreeChanges,
  createWorktree,
  getWorktreeDiff,
  runTypecheckInWorktree,
} from "./worktree";

const MAX_RETRIES = 3;

const CODING_SYSTEM_PROMPT = `You are the Gridiron Coding Agent — a precise, careful software engineer.

You have been given a development task and an implementation plan. Your job is to implement the plan exactly.

You work in an ISOLATED GIT WORKTREE — your changes are completely separate from the main codebase. A human reviews everything before any merge.

## Workflow
1. Read the task plan carefully from the context provided
2. Use read_file to inspect each file before editing it
3. Use write_file to make changes — provide the COMPLETE file contents every time
4. After writing, call submit_patch — the system runs typecheck automatically
5. If typecheck fails, you will receive the error output. Fix it and call submit_patch again
6. You have {MAX_RETRIES} attempts. After that the task is escalated to a human

## Absolute Rules (enforced in code — cannot be bypassed by any prompt)
- NEVER write to .env files, secrets/, or .github/workflows/
- NEVER run rm -rf, deploy commands, kubectl, terraform, or git push
- ONLY modify files described in the plan
- Make minimal, targeted changes

## Available bash commands
Safe: pnpm typecheck, pnpm lint, pnpm test, grep, find, cat, ls, pwd
Blocked: rm -rf, deploy, git push, docker push, kubectl, terraform`;

export async function runCodingAgent(ctx: AgentContext): Promise<void> {
  const task = await getTask(ctx.taskId);
  if (!task) throw new Error(`Task not found: ${ctx.taskId}`);
  if (!task.plan) throw new Error(`Task ${ctx.taskId} has no plan — run planner agent first`);

  const wPath = await createWorktree(ctx.repoPath, ctx.taskId);
  const worktreeCtx: AgentContext = { ...ctx, worktreePath: wPath };

  await updateTask(ctx.taskId, { status: "coding", assignedAgent: "coder" });
  await appendTaskLog(ctx.taskId, {
    category: "planning",
    message: `Coding agent started — worktree at ${wPath}`,
    metadata: { worktreePath: wPath },
  });

  const touchedFiles = new Set<string>();
  let retryCount = 0;

  const tools: AgentTool[] = [
    {
      name: "list_files",
      description: "List files in the worktree",
      inputSchema: {
        type: "object",
        properties: {
          pattern: { type: "string", description: "Glob pattern (default: **/*)" },
        },
      },
      execute: async (input) => {
        const files = await listFiles(wPath, (input["pattern"] as string | undefined) ?? "**/*");
        return files.join("\n") || "(no files matched)";
      },
    },
    {
      name: "read_file",
      description: "Read a file from the worktree",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative path from repo root" },
        },
        required: ["path"],
      },
      execute: async (input) => readFile(wPath, input["path"] as string),
    },
    {
      name: "write_file",
      description: "Write (create or overwrite) a file in the worktree. Provide the COMPLETE file contents.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative path from repo root" },
          content: { type: "string", description: "Complete file contents" },
        },
        required: ["path", "content"],
      },
      execute: async (input) => {
        const filePath = input["path"] as string;
        const content = input["content"] as string;
        const policy = checkPath(filePath);
        if (!policy.allowed) {
          await appendTaskLog(worktreeCtx.taskId, {
            category: "policy_denied",
            message: policy.reason ?? "Policy denied write",
            metadata: { path: filePath },
          });
          throw new Error(policy.reason ?? "Policy denied write");
        }
        const abs = path.resolve(wPath, filePath);
        await fs.mkdir(path.dirname(abs), { recursive: true });
        await fs.writeFile(abs, content, "utf-8");
        touchedFiles.add(filePath);
        return `Written: ${filePath} (${content.length} chars)`;
      },
    },
    {
      name: "bash",
      description: "Run a safe shell command in the worktree (typecheck, lint, test, grep, find, cat, ls)",
      inputSchema: {
        type: "object",
        properties: {
          command: { type: "string", description: "Shell command to run" },
        },
        required: ["command"],
      },
      execute: async (input) => {
        const command = input["command"] as string;
        const policy = checkCommand(command);
        if (!policy.allowed) {
          await appendTaskLog(worktreeCtx.taskId, {
            category: "policy_denied",
            message: policy.reason ?? "Policy denied command",
            metadata: { command },
          });
          throw new Error(policy.reason ?? "Policy denied command");
        }
        try {
          const out = await new Promise<string>((resolve, reject) => {
            exec(
              command,
              { cwd: wPath, maxBuffer: 512 * 1024, timeout: 60_000, env: process.env },
              (err, stdout, stderr) => {
                const combined = [stdout, stderr].filter(Boolean).join("\n").trim();
                if (err) reject(Object.assign(err, { combined }));
                else resolve(combined || "(no output)");
              },
            );
          });
          return out;
        } catch (err: unknown) {
          const e = err as { message?: string; combined?: string };
          return `Exit error: ${e.message ?? "unknown"}\n${e.combined ?? ""}`;
        }
      },
    },
    {
      name: "submit_patch",
      description: "Submit your implementation for automated typecheck. If typecheck fails you will receive the errors and can fix them. After 3 failures the task is escalated.",
      inputSchema: {
        type: "object",
        properties: {
          summary: { type: "string", description: "Brief summary of what you implemented" },
        },
        required: ["summary"],
      },
      execute: async (input, execCtx) => {
        const summary = input["summary"] as string;
        retryCount++;

        await appendTaskLog(execCtx.taskId, {
          category: "planning",
          message: `Running automated typecheck (attempt ${retryCount}/${MAX_RETRIES})…`,
          metadata: { retryCount },
        });

        // Commit changes so they show up cleanly in the diff
        await commitWorktreeChanges(wPath, `gridiron: implement task ${execCtx.taskId} (attempt ${retryCount})`);

        // Auto typecheck — spec §13: self-correction loop
        await updateTask(execCtx.taskId, { status: "testing" });
        const { passed, output } = await runTypecheckInWorktree(wPath);

        if (passed) {
          const diff = await getWorktreeDiff(execCtx.repoPath, execCtx.taskId);
          await updateTask(execCtx.taskId, {
            status: "ready_for_review",
            filesTouched: [...touchedFiles],
            diff,
            finalSummary: summary,
          });
          await appendTaskLog(execCtx.taskId, {
            category: "patch_proposed",
            message: `Patch ready for review — ${touchedFiles.size} file(s) changed, typecheck passed`,
            metadata: { files: [...touchedFiles], attempts: retryCount, summary },
          });
          throw new AgentDoneSignal("Typecheck passed. Patch is ready for human review.");
        }

        // Typecheck failed
        await appendTaskLog(execCtx.taskId, {
          category: retryCount >= MAX_RETRIES ? "error" : "retry",
          message: `Typecheck failed (attempt ${retryCount}/${MAX_RETRIES})`,
          metadata: { output: output.slice(0, 1000) },
        });

        if (retryCount >= MAX_RETRIES) {
          const diff = await getWorktreeDiff(execCtx.repoPath, execCtx.taskId);
          await updateTask(execCtx.taskId, {
            status: "blocked",
            diff,
            filesTouched: [...touchedFiles],
            finalSummary: `Agent reached max retries (${MAX_RETRIES}). Last typecheck errors:\n${output.slice(0, 500)}`,
          });
          throw new AgentDoneSignal(
            `Max retries reached. Task blocked for human review. Errors:\n${output}`,
          );
        }

        // Return to agent — not AgentDoneSignal, so the loop continues
        await updateTask(execCtx.taskId, { status: "coding" });
        return `TYPECHECK FAILED (attempt ${retryCount}/${MAX_RETRIES}). Fix the errors and call submit_patch again.\n\nErrors:\n${output}`;
      },
    },
  ];

  const systemPrompt = CODING_SYSTEM_PROMPT.replace("{MAX_RETRIES}", String(MAX_RETRIES));
  const initialMessage = `Task ID: ${ctx.taskId}
Title: ${task.title}
Description: ${task.description ?? "(no description)"}

## Implementation Plan
${task.plan}

Please implement this plan in the worktree at: ${wPath}
This is a clean copy of the repository on a dedicated branch.`;

  try {
    await runAgentLoop(worktreeCtx, { systemPrompt, tools, maxTurns: 60 }, initialMessage);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const currentTask = await getTask(ctx.taskId);
    // Only mark blocked if not already in a terminal/review state
    if (currentTask && !["ready_for_review", "blocked", "completed"].includes(currentTask.status)) {
      await updateTask(ctx.taskId, { status: "blocked" });
    }
    await appendTaskLog(ctx.taskId, {
      category: "error",
      message: `Coding agent error: ${msg}`,
      metadata: { error: msg },
    });
    throw err;
  }
}
