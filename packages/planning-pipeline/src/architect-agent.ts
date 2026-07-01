import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import type { ContextResult } from "@gridiron/context-builder";
import type { DevTask } from "@gridiron/shared-types";
import { ArchitectPlanSchema, type ArchitectPlan, type PmBrief } from "./types";

const MODEL = process.env["AGENT_MODEL"] ?? "claude-sonnet-4-6";

const ARCHITECT_SYSTEM_PROMPT = `You are an Architect Agent for Gridiron AI Developer Department.

Your role: given a PM brief and codebase context, produce a concrete technical plan.

Output ONLY valid JSON matching this schema:
{
  "technicalApproach": "string",         // paragraph describing the implementation approach
  "impactedSystems": ["string"],         // top-level packages/apps affected (e.g. "packages/task-engine")
  "impactedFiles": ["string"],           // specific files that need changes
  "risks": ["string"],                   // technical risks and mitigation ideas
  "testingStrategy": "string",           // how to validate the changes
  "implementationNotes": "string"        // concrete guidance for the coding agent
}

Reference real file paths from the context. Be specific and technical. Avoid vague advice.`;

function parseJsonSafe<T>(text: string, schema: z.ZodType<T>): T | null {
  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) return null;
  try {
    const parsed = JSON.parse(jsonMatch[0]);
    return schema.parse(parsed);
  } catch {
    return null;
  }
}

export async function runArchitectAgent(
  task: DevTask,
  pmBrief: PmBrief,
  context: ContextResult,
): Promise<ArchitectPlan> {
  const client = new Anthropic({ apiKey: process.env["ANTHROPIC_API_KEY"] });

  const userMessage = `Task: ${task.title}

PM Brief:
Goals: ${pmBrief.goals.join("; ")}
Constraints: ${pmBrief.constraints.join("; ")}
Acceptance Criteria: ${pmBrief.acceptanceCriteria.join("; ")}
Risk Areas: ${pmBrief.riskAreas.join("; ")}
Complexity: ${pmBrief.estimatedComplexity}

Codebase Context:
${context.summary}

Top relevant files:
${context.relevantFiles
  .slice(0, 10)
  .map((f) => `- ${f.filePath}`)
  .join("\n")}

Dependency chain (files importing the above):
${context.dependencyChain.slice(0, 5).join("\n")}

Related symbols:
${context.relatedSymbols.slice(0, 10).join("\n")}

Produce the Architect Plan JSON now.`;

  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 2048,
    system: ARCHITECT_SYSTEM_PROMPT,
    messages: [{ role: "user", content: userMessage }],
  });

  const content = response.content[0];
  if (!content || content.type !== "text") {
    throw new Error("Architect Agent returned no text response");
  }

  const plan = parseJsonSafe(content.text, ArchitectPlanSchema);
  if (!plan) {
    throw new Error(`Architect Agent returned invalid JSON:\n${content.text.slice(0, 500)}`);
  }

  return plan;
}
