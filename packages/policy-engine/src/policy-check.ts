export interface PolicyResult {
  allowed: boolean;
  reason?: string;
}

// Paths the agent may never write to, ever — spec 13_Policy_Engine_Specification.md v1
const DENIED_PATH_PATTERNS: RegExp[] = [
  /(?:^|\/)\.env(?:\.\w+)?$/i,          // .env, .env.local, .env.production
  /(?:^|\/)secrets\//i,                  // secrets/ directory anywhere in path
  /\.github\/workflows\//i,             // GitHub Actions workflows
  /(?:^|\/)node_modules\//i,            // never touch node_modules
  /(?:^|\/)\.git\//i,                   // git internals
];

// Shell commands that may never be executed by an agent
const DENIED_COMMAND_PATTERNS: RegExp[] = [
  /\brm\s+-rf\b/i,                                    // destructive delete
  /\bkubectl\s+apply\b/i,                             // k8s deployment
  /\bterraform\s+apply\b/i,                           // infra deployment
  /\bgit\s+push\s+(?:-f|--force)/i,                  // force push
  /\bgit\s+push\b.*\bmain\b/i,                        // push to main
  /\bgit\s+push\b.*\bmaster\b/i,                      // push to master
  /\bdocker\s+push\b/i,                               // image push
  /\bnpm\s+publish\b/i,                               // npm publish
  /\bpnpm\s+publish\b/i,                              // pnpm publish
  /\bvercel\b/i,                                      // Vercel CLI (any usage)
  /\bheroku\b/i,                                      // Heroku CLI
  /(?:^|\s)(?:npm|pnpm|yarn)\s+(?:run\s+)?deploy\b/i, // npm/pnpm run deploy
];

export function checkPath(filePath: string): PolicyResult {
  for (const pattern of DENIED_PATH_PATTERNS) {
    if (pattern.test(filePath)) {
      return {
        allowed: false,
        reason: `Policy denied: path "${filePath}" matches protected pattern (${pattern.source})`,
      };
    }
  }
  return { allowed: true };
}

export function checkPathInWorktree(filePath: string, worktreePath: string): PolicyResult {
  const { resolve, normalize } = require("path") as typeof import("path");
  const absWorktree = normalize(resolve(worktreePath));
  const absFile = filePath.startsWith("/")
    ? normalize(filePath)
    : normalize(resolve(worktreePath, filePath));

  if (!absFile.startsWith(absWorktree + "/") && absFile !== absWorktree) {
    return {
      allowed: false,
      reason: `Policy denied: path "${filePath}" escapes worktree boundary "${worktreePath}"`,
    };
  }
  return checkPath(filePath);
}

export function checkCommand(command: string): PolicyResult {
  for (const pattern of DENIED_COMMAND_PATTERNS) {
    if (pattern.test(command)) {
      return {
        allowed: false,
        reason: `Policy denied: command matches restricted pattern (${pattern.source})`,
      };
    }
  }
  return { allowed: true };
}
