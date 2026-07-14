"use client";

// Backend stores snake_case keys directly from agent tool calls.
// These interfaces match what the API actually returns.
interface PmBrief {
  goals: string[];
  constraints: string[];
  acceptance_criteria: string[];
  out_of_scope: string[];
  // optional legacy fields
  acceptanceCriteria?: string[];
  riskAreas?: string[];
  estimatedComplexity?: "low" | "medium" | "high";
}

interface ArchitectRisk {
  severity: string;
  description: string;
}

interface ArchitectFile {
  path: string;
  reason: string;
}

interface ArchitectPlan {
  // snake_case from backend
  technical_approach?: string;
  impacted_files?: (ArchitectFile | string)[];
  risks?: (ArchitectRisk | string)[];
  risk_level?: string;
  // camelCase legacy (kept for forward compat)
  technicalApproach?: string;
  impactedFiles?: string[];
  implementationNotes?: string;
}

interface SubTask {
  id?: string | number;
  type: string;
  title: string;
  description: string;
  // backend returns snake_case from decomposer tool output
  files_to_edit?: string[];
  depends_on?: (string | number)[];
  // camelCase alias (legacy)
  filesToEdit?: string[];
  dependsOn?: (string | number)[];
}

interface PipelineState {
  taskId: number;
  stage: string;
  pmBrief: PmBrief | null;
  architectPlan: ArchitectPlan | null;
  subtasks: SubTask[] | null;
  approved: boolean;
  error?: string | null;
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
  // Planning pipeline stages (actual backend stage names)
  pm: "PM Agent running…",
  architect: "Architect Agent running…",
  decomposer: "Task Decomposer running…",
  awaiting_approval: "Awaiting human approval",
  approved: "Approved",
  done: "Planning complete",
  rejected: "Plan rejected",
  error: "Pipeline error",
  blocked: "Pipeline blocked",
  // Coding pipeline stages (Phase 4)
  dev_running: "Dev → QA → Review pipeline running…",
  qa_running: "QA agent running…",
  review_running: "Reviewer agent running…",
  dev_complete: "Coding pipeline complete — diff ready",
};

const PLANNING_STAGES = ["pm", "architect", "decomposer"];
const CODING_STAGES = ["dev_running", "qa_running", "review_running"];

export function PipelineView({ pipeline }: Props) {
  const isPlanningRunning = PLANNING_STAGES.includes(pipeline.stage);
  const isCodingRunning = CODING_STAGES.includes(pipeline.stage);
  const isCodingDone = pipeline.stage === "dev_complete";

  return (
    <div className="space-y-4">
      {/* Stage indicator */}
      <div className="flex items-center gap-3">
        <div
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            pipeline.stage === "awaiting_approval"
              ? "bg-amber-100 text-amber-800"
              : pipeline.stage === "dev_complete"
              ? "bg-green-100 text-green-800"
              : pipeline.stage === "done"
              ? "bg-green-100 text-green-800"
              : pipeline.stage === "rejected" || pipeline.stage === "blocked"
              ? "bg-red-100 text-red-800"
              : pipeline.stage === "error"
              ? "bg-red-100 text-red-800"
              : isCodingRunning
              ? "bg-teal-100 text-teal-800"
              : "bg-blue-100 text-blue-800"
          }`}
        >
          {stageLabel[pipeline.stage] ?? pipeline.stage}
        </div>
        {(isPlanningRunning || isCodingRunning) && (
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
            {pipeline.pmBrief.estimatedComplexity && (
              <span className={`ml-auto text-xs font-normal ${complexityColor(pipeline.pmBrief.estimatedComplexity)}`}>
                Complexity: {pipeline.pmBrief.estimatedComplexity}
              </span>
            )}
          </h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {pipeline.pmBrief.goals?.length > 0 && <Section title="Goals" items={pipeline.pmBrief.goals} />}
            {(pipeline.pmBrief.acceptance_criteria ?? pipeline.pmBrief.acceptanceCriteria ?? []).length > 0 && (
              <Section title="Acceptance Criteria" items={pipeline.pmBrief.acceptance_criteria ?? pipeline.pmBrief.acceptanceCriteria ?? []} />
            )}
            {pipeline.pmBrief.constraints?.length > 0 && <Section title="Constraints" items={pipeline.pmBrief.constraints} />}
            {pipeline.pmBrief.out_of_scope?.length > 0 && <Section title="Out of Scope" items={pipeline.pmBrief.out_of_scope} />}
            {(pipeline.pmBrief.riskAreas ?? []).length > 0 && <Section title="Risk Areas" items={pipeline.pmBrief.riskAreas!} />}
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
            {pipeline.architectPlan.technical_approach ?? pipeline.architectPlan.technicalApproach}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {(pipeline.architectPlan.impacted_files ?? pipeline.architectPlan.impactedFiles ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wide">Impacted Files</p>
                <ul className="space-y-0.5">
                  {(pipeline.architectPlan.impacted_files ?? pipeline.architectPlan.impactedFiles ?? []).map((f, i) => {
                    const label = typeof f === "string" ? f : f.path;
                    const note = typeof f === "object" ? f.reason : undefined;
                    return (
                      <li key={i} className="font-mono text-xs text-slate-700">
                        {label}
                        {note && <span className="ml-1 font-sans text-slate-400">({note})</span>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            {(pipeline.architectPlan.risks ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold text-slate-500 uppercase tracking-wide">Risks</p>
                <ul className="space-y-1">
                  {(pipeline.architectPlan.risks ?? []).map((r, i) => {
                    const text = typeof r === "string" ? r : r.description;
                    const sev = typeof r === "object" ? r.severity : undefined;
                    const sevColor = sev === "high" ? "text-red-500" : sev === "medium" ? "text-amber-500" : "text-slate-400";
                    return (
                      <li key={i} className="text-xs text-slate-700 flex gap-1">
                        {sev && <span className={`font-semibold uppercase ${sevColor}`}>[{sev}]</span>}
                        <span>• {text}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
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
            {pipeline.subtasks.map((st, idx) => {
              const files = st.files_to_edit ?? st.filesToEdit ?? [];
              return (
                <div key={st.id ?? idx} className="rounded border border-slate-200 bg-white p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${subtaskTypeColor(st.type)}`}>
                      {st.type}
                    </span>
                    <span className="text-sm font-medium text-slate-800">{st.title}</span>
                  </div>
                  <p className="mb-2 text-xs text-slate-600">{st.description}</p>
                  {files.length > 0 && (
                    <div className="font-mono text-xs text-slate-500">
                      {files.map((f) => (
                        <span key={f} className="mr-2 inline-block">{f}</span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Dev → QA → Review pipeline (Phase 4) */}
      {(isCodingRunning || isCodingDone) && (
        <div className="rounded-lg border border-teal-200 bg-teal-50 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-teal-800">
            <span className="rounded bg-teal-100 px-2 py-0.5 text-xs text-teal-700">Coding Pipeline</span>
            Dev → QA → Review
            {isCodingRunning && (
              <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-teal-500" />
            )}
            {isCodingDone && (
              <span className="ml-auto rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                Complete
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            {[
              { label: "Dev Agent", stage: "dev_running", icon: "💻" },
              { label: "QA Agent", stage: "qa_running", icon: "🧪" },
              { label: "Reviewer", stage: "review_running", icon: "🔍" },
            ].map(({ label, stage, icon }, idx) => {
              const isActive = pipeline.stage === stage;
              const isPast = isCodingDone ||
                (stage === "dev_running" && ["qa_running", "review_running"].includes(pipeline.stage)) ||
                (stage === "qa_running" && pipeline.stage === "review_running");
              return (
                <div key={stage} className="flex items-center gap-2">
                  {idx > 0 && <span className="text-teal-300">→</span>}
                  <div
                    className={`rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                      isActive
                        ? "border-teal-400 bg-teal-100 text-teal-800"
                        : isPast
                        ? "border-green-300 bg-green-50 text-green-700"
                        : "border-slate-200 bg-white text-slate-500"
                    }`}
                  >
                    <span className="mr-1">{icon}</span>
                    {label}
                    {isActive && <span className="ml-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-teal-500 align-middle" />}
                    {isPast && <span className="ml-1 text-green-600">✓</span>}
                  </div>
                </div>
              );
            })}
          </div>
          {isCodingDone && (
            <p className="mt-3 text-xs text-teal-700">All subtasks passed QA and review — diff is ready for human approval.</p>
          )}
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
