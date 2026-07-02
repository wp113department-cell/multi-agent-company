export interface AgentContext {
  taskId: string;
  repoPath: string;
  worktreePath?: string;
  agentRunId?: string;
}

export interface AgentTool {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, { type: string; description: string }>;
    required?: string[];
  };
  execute: (input: Record<string, unknown>, ctx: AgentContext) => Promise<string>;
}

export class AgentDoneSignal {
  constructor(public readonly message: string) {}
}
