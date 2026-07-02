import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { getConfig } from "@gridiron/shared-config";
import type { ContextResult } from "@gridiron/context-builder";
import type { DevTask } from "@gridiron/shared-types";
import { PmBriefSchema, type PmBrief } from "./types";
import { loadRole } from "./load-role";

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
  const systemPrompt = await loadRole("pm");
  const config = getConfig();
  const client = new Anthropic({ apiKey: config.ANTHROPIC_API_KEY });

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
    model: config.MODEL_PLANNER,
    max_tokens: 1024,
    system: systemPrompt,
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
