import { z } from "zod";

const ConfigSchema = z.object({
  // Database
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),

  // Anthropic
  ANTHROPIC_API_KEY: z.string().min(1, "ANTHROPIC_API_KEY is required").optional(),

  // Model names (swappable without code changes)
  MODEL_PLANNER: z.string().default("claude-sonnet-4-6"),
  MODEL_CODER: z.string().default("claude-sonnet-4-6"),
  MODEL_ROUTER: z.string().default("claude-haiku-4-5-20251001"),

  // Voyage AI for embeddings
  VOYAGE_API_KEY: z.string().optional(),

  // Repo paths
  TARGET_REPO_PATH: z.string().default("."),
  WORKTREES_DIR: z.string().default("/tmp/gridiron/worktrees"),

  // Agent behaviour
  MAX_RETRIES: z.coerce.number().int().min(1).max(10).default(3),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),

  // Pipeline mode: 'simple' uses direct planner agent, 'full' uses PM→Architect→Decomposer
  PIPELINE_MODE: z.enum(["simple", "full"]).default("full"),

  // Context builder token budget (characters, not tokens — rough proxy)
  CONTEXT_BUDGET_CHARS: z.coerce.number().int().default(40000),
});

export type Config = z.infer<typeof ConfigSchema>;

let _config: Config | null = null;

export function getConfig(): Config {
  if (_config) return _config;

  const parsed = ConfigSchema.safeParse(process.env);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((i) => `  ${i.path.join(".")}: ${i.message}`)
      .join("\n");
    throw new Error(`Configuration error — check your .env file:\n${issues}`);
  }
  _config = parsed.data;
  return _config;
}

// Reset for testing
export function _resetConfig(): void {
  _config = null;
}
