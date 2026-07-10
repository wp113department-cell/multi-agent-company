"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DiffViewer } from "../../../components/DiffViewer";
import { PipelineView } from "../../../components/PipelineView";
import { StatusBadge } from "../../../components/StatusBadge";
import {
  approvePipeline,
  fetchArtifacts,
  fetchPipelineState,
  fetchTask,
  rejectPipeline,
  triggerAgentRun,
  triggerPipeline,
  updateTaskStatus,
} from "../../../lib/api";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const qc = useQueryClient();

  const { data: task, isLoading, error } = useQuery({
    queryKey: ["task", params.id],
    queryFn: () => fetchTask(params.id),
    refetchInterval: 3000,
  });

  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", params.id],
    queryFn: () => fetchPipelineState(params.id),
    refetchInterval: 4000,
    enabled: !!task,
  });

  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", params.id],
    queryFn: () => fetchArtifacts(params.id),
    refetchInterval: 5000,
    enabled: !!task,
  });

  const runMutation = useMutation({
    mutationFn: () => triggerAgentRun(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["task", params.id] }),
  });

  const runPipelineMutation = useMutation({
    mutationFn: () => triggerPipeline(params.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["pipeline", params.id] });
    },
  });

  const approvePipelineMutation = useMutation({
    mutationFn: () => approvePipeline(params.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["pipeline", params.id] });
    },
  });

  const rejectPipelineMutation = useMutation({
    mutationFn: () => rejectPipeline(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline", params.id] }),
  });

  const approveDiffMutation = useMutation({
    mutationFn: () => updateTaskStatus(params.id, "completed"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const rejectDiffMutation = useMutation({
    mutationFn: () => updateTaskStatus(params.id, "rejected"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const startCodingMutation = useMutation({
    mutationFn: () => triggerAgentRun(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["task", params.id] }),
  });

  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{(error as Error).message}</p>;
  if (!task) return null;

  const isActive = ["planning", "coding", "testing"].includes(task.status);
  const isPlanReview = task.status === "ready_for_review" && !!task.plan && !task.diff;
  const isDiffReview = task.status === "ready_for_review" && !!task.diff;
  const canRun = ["pending", "rejected"].includes(task.status);
  const isPipelineRunning = pipeline && ["pm_agent", "architect_agent", "task_decomposer"].includes(pipeline.stage);
  const isPipelineAwaitingApproval = pipeline?.stage === "awaiting_approval";
  const canRunPipeline = canRun && !isPipelineRunning && !isPipelineAwaitingApproval;

  return (
    <div className="space-y-6">
      <Link href="/tasks" className="text-sm text-slate-500 hover:underline">
        ← All tasks
      </Link>

      {/* Header */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">{task.title}</h1>
          <StatusBadge status={task.status} />
        </div>
        <p className="mb-3 text-sm text-slate-500 flex items-center gap-2 flex-wrap">
          <span>{task.priority} priority</span>
          {task.repoName ? (
            <span className="inline-flex items-center gap-1 rounded bg-indigo-50 border border-indigo-200 px-2 py-0.5 text-xs font-medium text-indigo-700">
              <span>📁</span> {task.repoName}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              Default repo
            </span>
          )}
        </p>
        {task.description && <p className="mb-4 text-sm text-slate-700">{task.description}</p>}

        {/* Agent controls */}
        <div className="flex flex-wrap gap-2">
          {canRunPipeline && (
            <button
              onClick={() => runPipelineMutation.mutate()}
              disabled={runPipelineMutation.isPending}
              className="rounded bg-violet-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {runPipelineMutation.isPending ? "Starting…" : "Run Planning Pipeline (PM → Architect → Decompose)"}
            </button>
          )}

          {canRun && !isPipelineRunning && !isPipelineAwaitingApproval && (
            <button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
              className="rounded border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {runMutation.isPending ? "Starting…" : "Run Planner Agent (quick)"}
            </button>
          )}

          {isPipelineRunning && (
            <span className="inline-flex items-center gap-1.5 rounded bg-violet-100 px-3 py-1.5 text-xs font-medium text-violet-800">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-violet-500" />
              Planning pipeline running…
            </span>
          )}

          {isPipelineAwaitingApproval && (
            <>
              <button
                onClick={() => approvePipelineMutation.mutate()}
                disabled={approvePipelineMutation.isPending}
                className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {approvePipelineMutation.isPending ? "Approving…" : "Approve Plan & Start Coding"}
              </button>
              <button
                onClick={() => rejectPipelineMutation.mutate()}
                disabled={rejectPipelineMutation.isPending}
                className="rounded border border-red-300 px-4 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Reject Pipeline Plan
              </button>
            </>
          )}

          {isActive && (
            <span className="inline-flex items-center gap-1.5 rounded bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-800">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
              Agent is working…
            </span>
          )}

          {isPlanReview && (
            <>
              <button
                onClick={() => startCodingMutation.mutate()}
                disabled={startCodingMutation.isPending}
                className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {startCodingMutation.isPending ? "Starting…" : "Approve Plan & Start Coding"}
              </button>
              <button
                onClick={() => rejectDiffMutation.mutate()}
                disabled={rejectDiffMutation.isPending}
                className="rounded border border-red-300 px-4 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Reject Plan
              </button>
            </>
          )}

          {isDiffReview && (
            <>
              <button
                onClick={() => approveDiffMutation.mutate()}
                disabled={approveDiffMutation.isPending}
                className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {approveDiffMutation.isPending ? "Approving…" : "Approve & Complete"}
              </button>
              <button
                onClick={() => rejectDiffMutation.mutate()}
                disabled={rejectDiffMutation.isPending}
                className="rounded border border-red-300 px-4 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Reject Diff
              </button>
            </>
          )}
        </div>

        {(runMutation.isError || startCodingMutation.isError || runPipelineMutation.isError) && (
          <p className="mt-2 text-xs text-red-600">
            {((runMutation.error ?? startCodingMutation.error ?? runPipelineMutation.error) as Error).message}
          </p>
        )}
      </div>

      {/* Planning Pipeline View (Phase 3) */}
      {pipeline && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-700">Planning Pipeline</h2>
          <PipelineView pipeline={pipeline as unknown as Parameters<typeof PipelineView>[0]["pipeline"]} />
        </div>
      )}

      {/* Implementation plan (from Phase 1/2 planner agent) */}
      {task.plan && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Implementation plan</h2>
          <pre className="whitespace-pre-wrap text-sm text-slate-800 leading-relaxed">{task.plan}</pre>
        </div>
      )}

      {/* Proposed diff */}
      {task.diff && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-1 text-sm font-semibold text-slate-700">Proposed code changes</h2>
          {task.finalSummary && (
            <p className="mb-3 text-sm text-slate-600 italic">{task.finalSummary}</p>
          )}
          <DiffViewer diff={task.diff} />
        </div>
      )}

      {/* Files touched */}
      {task.filesTouched.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Files changed</h2>
          <ul className="space-y-0.5">
            {task.filesTouched.map((f) => (
              <li key={f} className="font-mono text-xs text-slate-700">{f}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Final summary */}
      {task.finalSummary && !task.diff && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Summary</h2>
          <p className="text-sm text-slate-700">{task.finalSummary}</p>
        </div>
      )}

      {/* Pipeline Artifacts */}
      {artifacts && artifacts.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Pipeline Artifacts</h2>
          <div className="space-y-2">
            {artifacts.map((a) => (
              <div key={a.artifactId} className="flex items-center justify-between rounded border border-slate-100 bg-slate-50 px-3 py-2">
                <div>
                  <span className="rounded bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-700 mr-2">
                    {a.artifactType}
                  </span>
                  <span className="text-xs text-slate-500">by {a.createdByAgent}</span>
                  <span className="ml-2 text-xs text-slate-400">
                    {new Date(a.createdAt).toLocaleString()}
                  </span>
                </div>
                <a
                  href={`/api/artifacts/${a.artifactId}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
                >
                  View
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Log timeline */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Log timeline</h2>
        {task.logs.length === 0 && <p className="text-sm text-slate-500">No log entries yet.</p>}
        <ol className="space-y-3">
          {task.logs.map((log) => (
            <li key={log.logId} className="border-l-2 border-slate-200 pl-3">
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <span className={`font-mono uppercase ${logCategoryColor(log.category)}`}>
                  {log.category}
                </span>
                <span>{new Date(log.createdAt).toLocaleString()}</span>
              </div>
              <p className="text-sm text-slate-800">{log.message}</p>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function logCategoryColor(category: string): string {
  switch (category) {
    case "error": return "text-red-500";
    case "policy_denied": return "text-red-400";
    case "patch_proposed": return "text-green-600";
    case "planning": return "text-blue-500";
    case "retry": return "text-amber-500";
    case "warning": return "text-amber-500";
    default: return "text-slate-500";
  }
}
