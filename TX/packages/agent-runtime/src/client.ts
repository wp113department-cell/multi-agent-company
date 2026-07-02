import Anthropic from "@anthropic-ai/sdk";
import { getConfig } from "@gridiron/shared-config";

let _client: Anthropic | null = null;

export function getAnthropicClient(): Anthropic {
  if (!_client) {
    const config = getConfig();
    if (!config.ANTHROPIC_API_KEY) {
      throw new Error(
        "ANTHROPIC_API_KEY is not set. Add it to .env before running agents. " +
        "Agent runs are billable — see PROJECT.md for setup instructions.",
      );
    }
    _client = new Anthropic({ apiKey: config.ANTHROPIC_API_KEY });
  }
  return _client;
}

export function getPlannerModel(): string {
  return getConfig().MODEL_PLANNER;
}

export function getCoderModel(): string {
  return getConfig().MODEL_CODER;
}

export function getRouterModel(): string {
  return getConfig().MODEL_ROUTER;
}

export function getMaxRetries(): number {
  return getConfig().MAX_RETRIES;
}
