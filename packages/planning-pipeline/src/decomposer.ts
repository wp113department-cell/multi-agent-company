import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { SubTaskSchema, type ArchitectPlan, type PmBrief, type SubTask } from "./types";

const MODEL = process.env["AGENT_MODEL"] ?? "claude-sonnet-4-6";

const DECOMPOSER_SYSTEM_PROMPT = `You are a Task Decomposer for Gridiron AI Developer Department.

Your role: break a technical plan into concrete, assignable subtasks.

Output ONLY a valid JSON array matching this schema:
[
  {
    "id": "string",                        // short snake_case identifier (e.g. "add_db_column")
    "type": "backend|frontend|test|docs|config|migration",
    "title": "string",
    "description": "string",              // what exactly needs to be done
    "filesToEdit": ["string"],             // specific file paths to modify
    "dependsOn": ["string"]               // ids of subtasks that must complete first
  }
]

Rules:
- Maximum 8 subtasks
- Each subtask must be completable by a single coding agent in one pass
- filesToEdit should reference REAL files from the architect plan
- Use dependsOn to express ordering (e.g. migration before code, code before tests)`;

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
  const client = new Anthropic({ apiKey: process.env["ANTHROPIC_API_KEY"] });

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
    model: MODEL,
    max_tokens: 2048,
    system: DECOMPOSER_SYSTEM_PROMPT,
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
