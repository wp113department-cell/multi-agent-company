import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import type { ContextResult } from "@gridiron/context-builder";
import type { DevTask } from "@gridiron/shared-types";
import { PmBriefSchema, type PmBrief } from "./types";

const MODEL = process.env["AGENT_MODEL"] ?? "claude-sonnet-4-6";

const PM_SYSTEM_PROMPT = `You are a Product Manager Agent for Gridiron AI Developer Department.

Your role: translate a development task into a structured PM brief that guides the technical team.

You will be given:
1. The task title and description
2. A context summary of the relevant codebase files and symbols

Output ONLY valid JSON matching this schema:
{
  "goals": ["string"],                   // 2-5 clear goals this task achieves
  "constraints": ["string"],             // things the implementation MUST NOT do
  "acceptanceCriteria": ["string"],      // testable conditions that define "done"
  "riskAreas": ["string"],               // parts of the codebase that could break
  "estimatedComplexity": "low|medium|high"
}

Be specific, actionable, and reference actual file paths from the context when relevant.`;

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

export async function runPmAgent(task: DevTask, context: ContextResult): Promise<PmBrief> {
  const client = new Anthropic({ apiKey: process.env["ANTHROPIC_API_KEY"] });

  const userMessage = `Task: ${task.title}

Description: ${task.description ?? "(no description)"}

Codebase Context:
${context.summary}

Relevant files (top matches):
${context.relevantFiles
  .slice(0, 8)
  .map((f) => `- ${f.filePath} (score: ${f.score}, keywords: ${f.matchedKeywords.join(", ")})`)
  .join("\n")}

Related symbols:
${context.relatedSymbols.slice(0, 10).join("\n")}

Produce the PM Brief JSON now.`;

  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 1024,
    system: PM_SYSTEM_PROMPT,
    messages: [{ role: "user", content: userMessage }],
  });

  const content = response.content[0];
  if (!content || content.type !== "text") {
    throw new Error("PM Agent returned no text response");
  }

  const brief = parseJsonSafe(content.text, PmBriefSchema);
  if (!brief) {
    throw new Error(`PM Agent returned invalid JSON:\n${content.text.slice(0, 500)}`);
  }

  return brief;
}
