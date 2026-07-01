import { appendTaskLog, getTask, updateTask } from "@gridiron/task-engine";
import { grepFiles, gitLog, listFiles, readFile } from "@gridiron/repo-tools";
import { runAgentLoop } from "./base-agent";
import { AgentDoneSignal, type AgentContext, type AgentTool } from "./types";

const PLANNER_SYSTEM_PROMPT = `You are the Gridiron Planner Agent — the first step in the Gridiron AI Developer Department.

Your job: explore the codebase and produce a precise, actionable implementation plan for the given development task.

You have READ-ONLY access to the repository. You cannot modify any files.

## Workflow
1. Start with list_files() to understand the project structure
2. Read the most relevant source files based on the task
3. Use grep_files() to find specific function names, types, or patterns
4. Review git_log() to understand recent activity
5. Synthesize your findings into a complete plan

## Your Plan Must Include
- Summary: what changes are needed (2-4 sentences)
- Files to change: exact relative paths + what to change in each
- New files to create (if any): path and purpose
- Implementation order if dependencies exist
- Risks and edge cases
- Complexity estimate: simple | moderate | complex

## Critical Rules
- Only reference files and functions that actually exist — verify first
- Be specific enough that a coding agent can implement without guessing
- Describe changes in plain English, not code
- Call submit_plan when you have a complete, grounded plan`;

export async function runPlannerAgent(ctx: AgentContext): Promise<void> {
  const task = await getTask(ctx.taskId);
  if (!task) throw new Error(`Task not found: ${ctx.taskId}`);

  await updateTask(ctx.taskId, { status: "planning", assignedAgent: "planner" });
  await appendTaskLog(ctx.taskId, {
    category: "planning",
    message: "Planner agent started — exploring repository",
    metadata: { repoPath: ctx.repoPath },
  });

  const tools: AgentTool[] = [
    {
      name: "list_files",
      description: "List files in the repository matching an optional glob pattern",
      inputSchema: {
        type: "object",
        properties: {
          pattern: { type: "string", description: "Glob pattern (default: **/*). Example: packages/**/*.ts" },
        },
      },
      execute: async (input) => {
        const files = await listFiles(ctx.repoPath, (input["pattern"] as string | undefined) ?? "**/*");
        return files.join("\n") || "(no files matched)";
      },
    },
    {
      name: "read_file",
      description: "Read the contents of a file from the repository",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative path from repo root, e.g. packages/shared-types/src/dev-task.ts" },
        },
        required: ["path"],
      },
      execute: async (input) => {
        return readFile(ctx.repoPath, input["path"] as string);
      },
    },
    {
      name: "grep_files",
      description: "Search for a text query across source files. Returns matching lines with file and line number.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Text or identifier to search for" },
          file_glob: { type: "string", description: "Optional glob to limit which files to search (default: **/*.{ts,tsx,js,json,md})" },
        },
        required: ["query"],
      },
      execute: async (input) => {
        const results = await grepFiles(
          ctx.repoPath,
          input["query"] as string,
          (input["file_glob"] as string | undefined) ?? "**/*.{ts,tsx,js,jsx,json,md,sql}",
        );
        if (results.length === 0) return "(no matches found)";
        return results.map((r) => `${r.file}:${r.line}: ${r.content}`).join("\n");
      },
    },
    {
      name: "git_log",
      description: "Get recent git commit history to understand what has been changing",
      inputSchema: {
        type: "object",
        properties: {
          n: { type: "string", description: "Number of commits to show (default: 20)" },
        },
      },
      execute: async (input) => {
        return gitLog(ctx.repoPath, Number(input["n"] ?? 20));
      },
    },
    {
      name: "submit_plan",
      description: "Submit your final implementation plan. Call this when you have a complete, grounded plan.",
      inputSchema: {
        type: "object",
        properties: {
          plan: { type: "string", description: "The complete implementation plan in markdown" },
        },
        required: ["plan"],
      },
      execute: async (input, execCtx) => {
        const plan = input["plan"] as string;
        await updateTask(execCtx.taskId, {
          status: "ready_for_review",
          plan,
        });
        await appendTaskLog(execCtx.taskId, {
          category: "planning",
          message: "Implementation plan submitted — awaiting human review",
          metadata: { planLength: plan.length },
        });
        throw new AgentDoneSignal("Plan submitted successfully. Task is now ready for review.");
      },
    },
  ];

  const initialMessage = `Task ID: ${ctx.taskId}
Title: ${task.title}
Description: ${task.description ?? "(no description provided)"}
Priority: ${task.priority}
Repository: ${ctx.repoPath}

Please explore the repository and produce an implementation plan for this task.`;

  try {
    await runAgentLoop(ctx, { systemPrompt: PLANNER_SYSTEM_PROMPT, tools, maxTurns: 30 }, initialMessage);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await updateTask(ctx.taskId, { status: "blocked" });
    await appendTaskLog(ctx.taskId, {
      category: "error",
      message: `Planner agent failed: ${msg}`,
      metadata: { error: msg },
    });
    throw err;
  }
}
