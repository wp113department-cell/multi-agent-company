import { z } from "zod";
import { appendTaskLog, getTask, updateTask } from "@gridiron/task-engine";
import { grepFiles, gitLog, listFiles, readFile } from "@gridiron/repo-tools";
import { runAgentLoop } from "./base-agent";
import { loadRole } from "./roles";
import { AgentDoneSignal, type AgentContext, type AgentTool } from "./types";

const PlanSchema = z.object({
  summary: z.string().min(20, "Plan summary must be at least 20 characters"),
  filesToChange: z.array(z.string()).min(1, "Plan must list at least one file to change"),
  complexity: z.enum(["simple", "moderate", "complex"]),
}).passthrough();

function validatePlan(planText: string): { valid: boolean; error?: string } {
  if (planText.length < 100) {
    return { valid: false, error: "Plan is too short (minimum 100 characters)" };
  }
  if (!planText.includes("##") && !planText.includes("**")) {
    return { valid: false, error: "Plan must use markdown formatting with headers or bold text" };
  }
  return { valid: true };
}

export async function runPlannerAgent(ctx: AgentContext): Promise<void> {
  const systemPrompt = await loadRole("planner");
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
        const validation = validatePlan(plan);
        if (!validation.valid) {
          return `Plan rejected: ${validation.error}. Please revise and resubmit.`;
        }
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
    await runAgentLoop(ctx, { systemPrompt, tools, maxTurns: 30 }, initialMessage);
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
