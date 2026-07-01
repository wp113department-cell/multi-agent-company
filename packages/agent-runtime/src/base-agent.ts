import type Anthropic from "@anthropic-ai/sdk";
import { appendTaskLog } from "@gridiron/task-engine";
import { AGENT_MODEL, getAnthropicClient } from "./client";
import { AgentDoneSignal, type AgentContext, type AgentTool } from "./types";

export interface AgentConfig {
  systemPrompt: string;
  tools: AgentTool[];
  maxTurns: number;
}

export async function runAgentLoop(
  ctx: AgentContext,
  config: AgentConfig,
  initialUserMessage: string,
): Promise<void> {
  const client = getAnthropicClient();
  const messages: Anthropic.MessageParam[] = [
    { role: "user", content: initialUserMessage },
  ];

  const anthropicTools: Anthropic.Tool[] = config.tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.inputSchema as Anthropic.Tool["input_schema"],
  }));

  for (let turn = 0; turn < config.maxTurns; turn++) {
    const response = await client.messages.create({
      model: AGENT_MODEL,
      max_tokens: 8192,
      system: config.systemPrompt,
      messages,
      tools: anthropicTools,
    });

    messages.push({ role: "assistant", content: response.content });

    if (response.stop_reason === "end_turn") break;

    if (response.stop_reason !== "tool_use") break;

    const toolResults: Anthropic.ToolResultBlockParam[] = [];

    for (const block of response.content) {
      if (block.type !== "tool_use") continue;

      const tool = config.tools.find((t) => t.name === block.name);
      if (!tool) {
        toolResults.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: `Unknown tool: ${block.name}`,
          is_error: true,
        });
        continue;
      }

      const input = block.input as Record<string, unknown>;

      try {
        const result = await tool.execute(input, ctx);
        await appendTaskLog(ctx.taskId, {
          category: "files_inspected",
          message: `[${block.name}] ${describeToolCall(block.name, input)}`,
          metadata: { tool: block.name, input, chars: result.length },
        });
        toolResults.push({ type: "tool_result", tool_use_id: block.id, content: result });
      } catch (err) {
        if (err instanceof AgentDoneSignal) {
          // Tool signalled completion — push result and return immediately
          toolResults.push({ type: "tool_result", tool_use_id: block.id, content: err.message });
          messages.push({ role: "user", content: toolResults });
          return;
        }
        const msg = err instanceof Error ? err.message : String(err);
        await appendTaskLog(ctx.taskId, {
          category: "error",
          message: `[${block.name}] error: ${msg}`,
          metadata: { tool: block.name, input, error: msg },
        });
        toolResults.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: `Error: ${msg}`,
          is_error: true,
        });
      }
    }

    messages.push({ role: "user", content: toolResults });
  }
}

function describeToolCall(name: string, input: Record<string, unknown>): string {
  const path = (input["path"] ?? input["file_path"] ?? input["pattern"] ?? "") as string;
  const query = (input["query"] ?? input["command"] ?? "") as string;
  if (path) return path;
  if (query) return String(query).slice(0, 80);
  return "";
}
