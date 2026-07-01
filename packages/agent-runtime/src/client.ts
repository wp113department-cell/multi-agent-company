import Anthropic from "@anthropic-ai/sdk";

let _client: Anthropic | null = null;

export function getAnthropicClient(): Anthropic {
  if (!_client) {
    const key = process.env["ANTHROPIC_API_KEY"];
    if (!key) {
      throw new Error(
        "ANTHROPIC_API_KEY is not set. Add it to .env before running agents. " +
        "Agent runs are billable — see PLAN.md for setup instructions.",
      );
    }
    _client = new Anthropic({ apiKey: key });
  }
  return _client;
}

export const AGENT_MODEL = process.env["AGENT_MODEL"] ?? "claude-sonnet-4-6";
