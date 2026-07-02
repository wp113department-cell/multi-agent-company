import { getConfig } from "@gridiron/shared-config";
import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { SubTaskSchema, type ArchitectPlan, type PmBrief, type SubTask } from "./types";
import { loadRole } from "./load-role";

function parseJsonSafe<T>(text: string, schema: z.ZodType<T>): T | null {
  const jsonMatch = text.match(/\[[\s\S]*\]/);
  if (!jsonMatch) return null;
  try {
    const parsed = JSON.parse(jsonMatch[0]);
    return schema.parse(parsed);
  } catch {
    return null;
  }
}

export async function runDecomposer(
  pmBrief: PmBrief,
  architectPlan: ArchitectPlan,
): Promise<SubTask[]> {
  const systemPrompt = await loadRole("decomposer");
  const config = getConfig();
  const client = new Anthropic({ apiKey: config.ANTHROPIC_API_KEY });

  const userMessage = `PM Brief Goals: ${pmBrief.goals.join("; ")}

Architect Plan:
${architectPlan.technicalApproach}

Impacted files:
${architectPlan.impactedFiles.join("\n")}

Implementation notes:
${architectPlan.implementationNotes}

Testing strategy: ${architectPlan.testingStrategy}

Produce the subtask JSON array now.`;

  const response = await client.messages.create({
    model: getConfig().MODEL_PLANNER,
    max_tokens: 2048,
    system: systemPrompt,
    messages: [{ role: "user", content: userMessage }],
  });

  const content = response.content[0];
  if (!content || content.type !== "text") {
    throw new Error("Decomposer returned no text response");
  }

  const subtasks = parseJsonSafe(content.text, z.array(SubTaskSchema));
  if (!subtasks) {
    throw new Error(`Decomposer returned invalid JSON:\n${content.text.slice(0, 500)}`);
  }

  return subtasks;
}
