"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DiffViewer } from "../../../components/DiffViewer";
import { PipelineView, type SubtaskEdit } from "../../../components/PipelineView";
import { StatusBadge } from "../../../components/StatusBadge";
import { useState } from "react";
import {
  approvePipeline,
  fetchArtifacts,
  fetchPipelineState,
  fetchTask,
  fetchTaskImages,
  fetchTaskPr,
  rateAgent,
  rejectPipeline,
  restartTask,
  retryTaskPush,
  triggerAgentRun,
  approveTaskPlan,
  triggerPipeline,
  triggerSmartRun,
  startTask,
  updateTaskStatus,
} from "../../../lib/api";
import { Icon } from "../../../components/Icon";

// #439 (2026-09-22, "User satisfaction — real, not proxy") — the backend
// endpoint (POST /api/ratings) existed with no way for a user to actually
// submit one. No GET-my-rating endpoint exists to check for a prior
// rating, so "already rated" is tracked only for this page view (resets on
// reload) — a deliberate, minimal scope match to what the backend exposes,
// not a persistence gap this component can fix on its own.
function AgentRatingWidget({ agentName, taskId }: { agentName: string; taskId: string }) {
  const [submitted, setSubmitted] = useState<1 | -1 | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (rating: 1 | -1) => {
    setPending(true);
    setError(null);
    try {
      await rateAgent({ agentName, rating, taskId });
      setSubmitted(rating);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };

  if (submitted !== null) {
    return (
      <p className="text-xs text-slate-500">
        <Icon name={submitted === 1 ? "thumbs-up" : "thumbs-down"} size={14} /> Thanks for the feedback on {agentName}&apos;s work.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500">Was {agentName}&apos;s work helpful?</span>
      <button
        type="button"
        onClick={() => void submit(1)}
        disabled={pending}
        aria-label="Thumbs up"
        className="rounded-full border border-slate-200 px-2 py-1 text-sm hover:bg-green-50 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-green-900/20"
      >
        <Icon name="thumbs-up" size={15} />
      </button>
      <button
        type="button"
        onClick={() => void submit(-1)}
        disabled={pending}
        aria-label="Thumbs down"
        className="rounded-full border border-slate-200 px-2 py-1 text-sm hover:bg-red-50 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-red-900/20"
      >
        <Icon name="thumbs-down" size={15} />
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}

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

  const { data: taskPr } = useQuery({
    queryKey: ["taskPr", params.id],
    queryFn: () => fetchTaskPr(params.id),
    refetchInterval: 5000,
    enabled: !!task,
  });

  const { data: taskImages } = useQuery({
    queryKey: ["taskImages", params.id],
    queryFn: () => fetchTaskImages(params.id),
    enabled: !!task,
  });

  const runMutation = useMutation({
    mutationFn: () => triggerAgentRun(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["task", params.id] }),
  });

  const startMutation = useMutation({
    mutationFn: () => startTask(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["task", params.id] }),
  });

  const smartRunMutation = useMutation({
    mutationFn: () => triggerSmartRun(params.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["pipeline", params.id] });
    },
  });

  const runPipelineMutation = useMutation({
    mutationFn: () => triggerPipeline(params.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["pipeline", params.id] });
    },
  });

  // #227 (2026-09-28) — human takeover: per-subtask edits/rejections
  // collected from PipelineView, applied as part of the same approval.
  const [subtaskEdits, setSubtaskEdits] = useState<SubtaskEdit[]>([]);

  const approvePipelineMutation = useMutation({
    mutationFn: () => approvePipeline(params.id, subtaskEdits),
    onSuccess: () => {
      setSubtaskEdits([]);
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["pipeline", params.id] });
    },
  });

  const rejectPipelineMutation = useMutation({
    mutationFn: () => rejectPipeline(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline", params.id] }),
  });

  const retryPushMutation = useMutation({
    mutationFn: () => retryTaskPush(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["taskPr", params.id] }),
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
    mutationFn: () => approveTaskPlan(params.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["task", params.id] }),
  });

  const restartMutation = useMutation({
    mutationFn: () => restartTask(params.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", params.id] });
      qc.invalidateQueries({ queryKey: ["pipeline", params.id] });
    },
  });

  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{(error as Error).message}</p>;
  if (!task) return null;

  const isActive = ["planning", "coding", "testing"].includes(task.status);
  const isPlanReview = task.status === "ready_for_review" && !!task.plan && !task.diff;
  const isDiffReview = task.status === "ready_for_review" && !!task.diff;
  const canRun = ["pending", "rejected"].includes(task.status);
  const canRestart = ["error", "failed", "blocked"].includes(task.status);
  const isPipelineRunning = task.status === "planning" && (!pipeline || pipeline.stage === "pm");
  const isPipelineAwaitingApproval = pipeline?.stage === "awaiting_approval";
  const canRunPipeline = canRun && !isPipelineRunning && !isPipelineAwaitingApproval;
  const actionError = startMutation.error ?? runMutation.error ?? startCodingMutation.error ??
    runPipelineMutation.error ?? smartRunMutation.error ?? restartMutation.error ??
    approveDiffMutation.error ?? rejectDiffMutation.error ?? approvePipelineMutation.error ??
    rejectPipelineMutation.error ?? retryPushMutation.error;

  return (
    <div className="space-y-6">
      <Link href="/tasks" className="text-sm text-slate-500 hover:underline">
        ← All tasks
      </Link>

      {/* Header */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h1 className="font-sans text-xl font-semibold leading-snug">{task.title}</h1>
          <div className="flex items-center gap-2">
            <Link
              href={`/stream/${params.id}`}
              className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              View live activity →
            </Link>
            <StatusBadge status={task.status} />
          </div>
        </div>
        <p className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1 rounded-full border border-orange-200 bg-orange-50 px-2.5 py-0.5 font-semibold text-orange-800">
            <Icon name="folder" size={12} /> {task.projectName ?? task.repoName ?? "No project"}
          </span>
          <span
            className={`rounded-full px-2.5 py-0.5 font-semibold ring-1 ${
              task.priority === "high" ? "bg-red-50 text-red-700 ring-red-200" : "bg-slate-50 text-slate-600 ring-slate-200"
            }`}
          >
            {task.priority === "high" ? "High" : task.priority === "low" ? "Low" : "Medium"} priority
          </span>
          <span
            className={`rounded-full px-2.5 py-0.5 font-semibold ring-1 ${
              task.executionMode === "max" ? "bg-orange-50 text-orange-700 ring-orange-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"
            }`}
          >
            {task.executionMode === "max" ? "Max" : "Economy"}
          </span>
          {task.goalTitle && <span className="rounded-full bg-slate-50 px-2.5 py-0.5 text-slate-600 ring-1 ring-slate-200 inline-flex items-center gap-1"><Icon name="target" size={12} /> {task.goalTitle}</span>}
          {task.epicTitle && <span className="rounded-full bg-slate-50 px-2.5 py-0.5 text-slate-600 ring-1 ring-slate-200 inline-flex items-center gap-1"><Icon name="layers" size={12} /> {task.epicTitle}</span>}
          <Link href={task.projectId ? `/chat?project=${task.projectId}` : "/chat"} className="ml-auto rounded-full border border-slate-200 px-2.5 py-0.5 font-medium text-slate-600 hover:bg-orange-50">
            <Icon name="message" size={12} /> Chat with the team
          </Link>
        </p>
        {task.description && <p className="mb-4 text-sm text-slate-700">{task.description}</p>}

        {(isPlanReview || isDiffReview || isPipelineAwaitingApproval) && (
          <div role="status" className="mb-4 flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            <Icon name="hand" size={22} className="text-amber-600" />
            <div>
              <p className="font-semibold">Your decision is needed</p>
              <p className="mt-0.5">
                {isDiffReview
                  ? "The team finished the code. Look at the changes below, then approve to complete the task or reject to send it back."
                  : "The team made a plan. Read it below, then approve to start coding or reject it."}{" "}
                Nothing continues until you choose.
              </p>
            </div>
          </div>
        )}

        {/* Agent controls */}
        <div className="flex flex-wrap gap-2">
          {canRunPipeline && (
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              title={task.executionMode === "max" ? "Runs the full team pipeline" : "Uses the fewest agents (Economy)"}
              className="rounded-lg bg-orange-600 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-1.5">{!startMutation.isPending && <Icon name="play" size={13} />}{startMutation.isPending ? "Starting…" : `Start (${task.executionMode === "max" ? "Max" : "Economy"})`}</span>
            </button>
          )}

          {canRunPipeline && (
            <details className="w-full text-sm">
              <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-800">
                Advanced start options
              </summary>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  onClick={() => smartRunMutation.mutate()}
                  disabled={smartRunMutation.isPending}
                  title="Picks the fewest agents for this task — a UI-only change uses only the UI agent; a new project uses the full pipeline."
                  className="rounded border border-emerald-300 px-4 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                >
                  {smartRunMutation.isPending ? "Starting…" : "Smart Run (recommended, cheapest)"}
                </button>
                <button
                  onClick={() => runPipelineMutation.mutate()}
                  disabled={runPipelineMutation.isPending}
                  className="rounded border border-violet-300 px-4 py-1.5 text-sm font-medium text-violet-700 hover:bg-violet-50 disabled:opacity-50"
                >
                  {runPipelineMutation.isPending ? "Starting…" : "Full Pipeline (PM → Architect → Decompose)"}
                </button>
                {canRun && !isPipelineRunning && !isPipelineAwaitingApproval && (
                  <button
                    onClick={() => runMutation.mutate()}
                    disabled={runMutation.isPending}
                    className="rounded border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {runMutation.isPending ? "Starting…" : "Run Planner Agent (quick)"}
                  </button>
                )}
              </div>
            </details>
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

          {canRestart && (
            <button
              onClick={() => restartMutation.mutate()}
              disabled={restartMutation.isPending}
              className="rounded bg-orange-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
            >
              {restartMutation.isPending ? "Restarting…" : "Restart pipeline"}
            </button>
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

        {actionError && (
          <p role="alert" className="mt-2 text-xs text-red-600">
            {actionError.message}
          </p>
        )}
      </div>

      {/* Reference images (Day 16 — Image Input Pipeline) */}
      {taskImages && taskImages.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Reference images</h2>
          <ul className="flex flex-wrap gap-3">
            {taskImages.map((img) => (
              <li key={img.id}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/tasks/${params.id}/images/${img.id}`}
                  alt={`Reference ${img.id}`}
                  className="h-28 w-28 rounded border border-slate-200 object-cover"
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Planning Pipeline View (Phase 3) */}
      {pipeline && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-700">Planning Pipeline</h2>
          <PipelineView
            pipeline={pipeline as unknown as Parameters<typeof PipelineView>[0]["pipeline"]}
            onSubtaskEditsChange={setSubtaskEdits}
          />
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

      {/* Git Push / Pull Request (Day 14) */}
      {taskPr && taskPr.branchName && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Git branch &amp; pull request</h2>
          <p className="mb-2 font-mono text-xs text-slate-700">{taskPr.branchName}</p>
          <div className="flex items-center gap-3">
            <span
              className={
                "rounded px-2 py-0.5 text-xs font-medium " +
                (taskPr.prStatus === "pushed"
                  ? "bg-green-100 text-green-800"
                  : taskPr.prStatus === "failed"
                  ? "bg-red-100 text-red-800"
                  : taskPr.prStatus === "pending"
                  ? "bg-amber-100 text-amber-800"
                  : "bg-slate-100 text-slate-600")
              }
            >
              {taskPr.prStatus}
            </span>
            {taskPr.prUrl && (
              <a
                href={taskPr.prUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 underline"
              >
                View pull request
              </a>
            )}
            {taskPr.prStatus === "failed" && (
              <button
                type="button"
                onClick={() => retryPushMutation.mutate()}
                disabled={retryPushMutation.isPending}
                className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {retryPushMutation.isPending ? "Retrying…" : "Retry push"}
              </button>
            )}
          </div>
          {retryPushMutation.isError && (
            <p className="mt-2 text-xs text-red-600">{(retryPushMutation.error as Error).message}</p>
          )}
        </div>
      )}

      {/* Final summary */}
      {task.finalSummary && !task.diff && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Summary</h2>
          <p className="text-sm text-slate-700">{task.finalSummary}</p>
        </div>
      )}

      {/* #439 — real user satisfaction rating, once there's finished work
          from a real agent to rate. */}
      {task.status === "completed" && task.assignedAgent && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <AgentRatingWidget agentName={task.assignedAgent} taskId={String(task.id)} />
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
