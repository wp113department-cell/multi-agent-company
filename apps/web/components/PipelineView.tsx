"use client";

interface PmBrief {
  goals: string[];
  constraints: string[];
  acceptanceCriteria: string[];
  riskAreas: string[];
  estimatedComplexity: "low" | "medium" | "high";
}

interface ArchitectPlan {
  technicalApproach: string;
  impactedSystems: string[];
  impactedFiles: string[];
  risks: string[];
  testingStrategy: string;
  implementationNotes: string;
}

interface SubTask {
  id: string;
  type: string;
  title: string;
  description: string;
  filesToEdit: string[];
  dependsOn: string[];
}

interface PipelineState {
  id: string;
  taskId: string;
  stage: string;
  pmBrief: PmBrief | null;
  architectPlan: ArchitectPlan | null;
  subtasks: SubTask[] | null;
  error: string | null;
  updatedAt: string;
}

interface Props {
  pipeline: PipelineState;
}

const complexityColor = (c: string) =>
  c === "high" ? "text-red-600" : c === "medium" ? "text-amber-600" : "text-green-600";

const subtaskTypeColor = (t: string) => {
  switch (t) {
    case "backend": return "bg-blue-100 text-blue-800";
    case "frontend": return "bg-purple-100 text-purple-800";
    case "test": return "bg-green-100 text-green-800";
    case "docs": return "bg-slate-100 text-slate-700";
    case "migration": return "bg-amber-100 text-amber-800";
    case "config": return "bg-indigo-100 text-indigo-800";
    default: return "bg-slate-100 text-slate-700";
  }
};

const stageLabel: Record<string, string> = {
  pm_agent: "PM Agent running…",
  architect_agent: "Architect Agent running…",
  task_decomposer: "Task Decomposer running…",
  awaiting_approval: "Awaiting human approval",
  approved: "Approved — coding agent running",
  rejected: "Plan rejected",
  error: "Pipeline error",
};

export function PipelineView({ pipeline }: Props) {
  const isRunning = ["pm_agent", "architect_agent", "task_decomposer"].includes(pipeline.stage);

  return (
    <div className="space-y-4">
      {/* Stage indicator */}
      <div className="flex items-center gap-3">
        <div
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            pipeline.stage === "awaiting_approval"
              ? "bg-amber-100 text-amber-800"
              : pipeline.stage === "approved"
              ? "bg-green-100 text-green-800"
              : pipeline.stage === "rejected"
              ? "bg-red-100 text-red-800"
              : pipeline.stage === "error"
              ? "bg-red-100 text-red-800"
              : "bg-blue-100 text-blue-800"
          }`}
        >
          {stageLabel[pipeline.stage] ?? pipeline.stage}
        </div>
        {isRunning && (
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
        )}
      </div>

      {pipeline.error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {pipeline.error}
        </div>
      )}

      {/* PM Brief */}
      {pipeline.pmBrief && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
            <span className="rounded bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">PM Agent</span>
            Product Brief
            <span className={`ml-auto text-xs font-normal ${complexityColor(pipeline.pmBrief.estimatedComplexity)}`}>
              Complexity: {pipeline.pmBrief.estimatedComplexity}
            </span>
          </h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Section title="Goals" items={pipeline.pmBrief.goals} />
            <Section title="Acceptance Criteria" items={pipeline.pmBrief.acceptanceCriteria} />
            <Section title="Constraints" items={pipeline.pmBrief.constraints} />
            <Section title="Risk Areas" items={pipeline.pmBrief.riskAreas} />
          </div>
        </div>
      )}

      {/* Architect Plan */}
      {pipeline.architectPlan && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
            <span className="rounded bg-violet-100 px-2 py-0.5 text-xs text-violet-700">Architect Agent</span>
            Technical Plan
          </h3>
          <p className="mb-3 text-sm text-slate-700 leading-relaxed">
            {pipeline.architectPlan.technicalApproach}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wide">Impacted Files</p>
              <ul className="space-y-0.5">
                {pipeline.architectPlan.impactedFiles.map((f) => (
                  <li key={f} className="font-mono text-xs text-slate-700">{f}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wide">Risks</p>
              <ul className="space-y-1">
                {pipeline.architectPlan.risks.map((r, i) => (
                  <li key={i} className="text-xs text-slate-700">• {r}</li>
                ))}
              </ul>
            </div>
          </div>
          {pipeline.architectPlan.implementationNotes && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wide">Implementation Notes</p>
              <p className="text-sm text-slate-700">{pipeline.architectPlan.implementationNotes}</p>
            </div>
          )}
        </div>
      )}

      {/* Subtasks */}
      {pipeline.subtasks && pipeline.subtasks.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
            <span className="rounded bg-teal-100 px-2 py-0.5 text-xs text-teal-700">Decomposer</span>
            Subtasks ({pipeline.subtasks.length})
          </h3>
          <div className="space-y-3">
            {pipeline.subtasks.map((st) => (
              <div key={st.id} className="rounded border border-slate-200 bg-white p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className={`rounded px-2 py-0.5 text-xs font-semibold ${subtaskTypeColor(st.type)}`}>
                    {st.type}
                  </span>
                  <span className="text-sm font-medium text-slate-800">{st.title}</span>
                </div>
                <p className="mb-2 text-xs text-slate-600">{st.description}</p>
                {st.filesToEdit.length > 0 && (
                  <div className="font-mono text-xs text-slate-500">
                    {st.filesToEdit.map((f) => (
                      <span key={f} className="mr-2 inline-block">{f}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wide">{title}</p>
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="text-xs text-slate-700">• {item}</li>
        ))}
      </ul>
    </div>
  );
}
