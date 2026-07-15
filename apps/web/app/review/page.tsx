"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface PendingEpic {
  epicId: string;
  title: string;
  status: string;
  costEstimate: number | null;
  haltReason: string | null;
  age: number;
  createdAt: string;
}

interface PendingTask {
  taskId: number;
  title: string;
  description: string;
  status: string;
  epicId: string | null;
  age: number;
  createdAt: string;
}

interface BatchReviewData {
  epics: PendingEpic[];
  tasks: PendingTask[];
  totalPendingReview: number;
}

// ──────────────────────────────────────────────────────────────────────────────
// API helpers
// ──────────────────────────────────────────────────────────────────────────────

async function fetchBatchReview(): Promise<BatchReviewData> {
  const res = await fetch("/api/epics/batch-review", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load batch review: ${res.status}`);
  return res.json();
}

async function approveEpic(epicId: string): Promise<void> {
  const res = await fetch(`/api/epics/${epicId}/approve`, { method: "POST" });
  if (!res.ok) throw new Error(`Approve failed: ${res.status}`);
}

async function rejectEpic(epicId: string): Promise<void> {
  const res = await fetch(`/api/epics/${epicId}/reject`, { method: "POST" });
  if (!res.ok) throw new Error(`Reject failed: ${res.status}`);
}

async function approveTask(taskId: number): Promise<void> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Task approve failed: ${res.status}`);
}

async function rejectTask(taskId: number): Promise<void> {
  const res = await fetch(`/api/tasks/${taskId}/pipeline/reject`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Task reject failed: ${res.status}`);
}

// ──────────────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────────────

function AgeChip({ hours }: { hours: number }) {
  const label =
    hours < 1
      ? `${Math.round(hours * 60)}m`
      : hours < 24
      ? `${Math.round(hours)}h`
      : `${Math.round(hours / 24)}d`;
  const cls =
    hours > 48
      ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
      : hours > 12
      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
      : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300";
  return (
    <span className={`text-xs rounded-full px-2 py-0.5 font-mono ${cls}`}>
      {label} old
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    ready_for_review: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
    pending_cost_approval:
      "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
    awaiting_approval: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  };
  const cls = map[status] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`text-xs font-semibold rounded-full px-2 py-0.5 ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Epic row
// ──────────────────────────────────────────────────────────────────────────────

function EpicRow({
  epic,
  onApprove,
  onReject,
}: {
  epic: PendingEpic;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-400 font-mono">EPIC</span>
            <StatusBadge status={epic.status} />
            <AgeChip hours={epic.age} />
          </div>
          <Link
            href={`/epics`}
            className="mt-1 font-medium text-gray-900 dark:text-gray-100 hover:underline line-clamp-1"
          >
            {epic.title}
          </Link>
          {epic.costEstimate !== null && (
            <p className="text-xs text-gray-500 mt-0.5">
              Estimated cost: ${epic.costEstimate.toFixed(4)}
            </p>
          )}
          {epic.haltReason && (
            <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
              ⚠ {epic.haltReason}
            </p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={() => onApprove(epic.epicId)}
            className="rounded bg-green-600 hover:bg-green-700 text-white text-xs px-3 py-1.5 font-medium transition-colors"
          >
            Approve
          </button>
          <button
            onClick={() => onReject(epic.epicId)}
            className="rounded bg-red-600 hover:bg-red-700 text-white text-xs px-3 py-1.5 font-medium transition-colors"
          >
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Task row
// ──────────────────────────────────────────────────────────────────────────────

function TaskRow({
  task,
  onApprove,
  onReject,
}: {
  task: PendingTask;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-400 font-mono">TASK #{task.taskId}</span>
            <StatusBadge status={task.status} />
            <AgeChip hours={task.age} />
            {task.epicId && (
              <span className="text-xs text-blue-600 dark:text-blue-400">
                epic: {task.epicId.slice(0, 8)}
              </span>
            )}
          </div>
          <Link
            href={`/tasks/${task.taskId}`}
            className="mt-1 font-medium text-gray-900 dark:text-gray-100 hover:underline line-clamp-1"
          >
            {task.title}
          </Link>
          {task.description && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
              {task.description}
            </p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={() => onApprove(task.taskId)}
            className="rounded bg-green-600 hover:bg-green-700 text-white text-xs px-3 py-1.5 font-medium transition-colors"
          >
            Approve
          </button>
          <button
            onClick={() => onReject(task.taskId)}
            className="rounded bg-red-600 hover:bg-red-700 text-white text-xs px-3 py-1.5 font-medium transition-colors"
          >
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Main page
// ──────────────────────────────────────────────────────────────────────────────

export default function BatchReviewPage() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<BatchReviewData>({
    queryKey: ["batch-review"],
    queryFn: fetchBatchReview,
    refetchInterval: 30_000,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["batch-review"] });

  const epicApproveMut = useMutation({
    mutationFn: approveEpic,
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const epicRejectMut = useMutation({
    mutationFn: rejectEpic,
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const taskApproveMut = useMutation({
    mutationFn: approveTask,
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const taskRejectMut = useMutation({
    mutationFn: rejectTask,
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const handleApproveAll = async () => {
    if (!data) return;
    setError(null);
    const epicPromises = data.epics.map((e) => approveEpic(e.epicId));
    const taskPromises = data.tasks.map((t) => approveTask(t.taskId));
    try {
      await Promise.all([...epicPromises, ...taskPromises]);
      invalidate();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const total = data?.totalPendingReview ?? 0;

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            Daily Batch Review
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            All epics and tasks awaiting human approval — sorted by age
          </p>
        </div>
        <div className="flex items-center gap-3">
          {total > 0 && (
            <span className="rounded-full bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200 text-sm font-semibold px-3 py-1">
              {total} pending
            </span>
          )}
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ["batch-review"] })}
            className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 border border-gray-200 dark:border-gray-600 rounded px-2 py-1 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-3 underline text-xs"
          >
            dismiss
          </button>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="text-center py-12 text-gray-400">Loading review queue…</div>
      )}

      {/* Error */}
      {isError && (
        <div className="text-center py-12 text-red-500">
          Failed to load batch review data. Is the backend running?
        </div>
      )}

      {/* Empty state */}
      {data && total === 0 && (
        <div className="text-center py-16 rounded-xl border border-dashed border-gray-300 dark:border-gray-600">
          <div className="text-4xl mb-3">✅</div>
          <p className="font-semibold text-gray-700 dark:text-gray-300">
            Nothing pending review
          </p>
          <p className="text-sm text-gray-400 mt-1">
            All epics and tasks are up to date.
          </p>
        </div>
      )}

      {/* Approve all */}
      {data && total > 0 && (
        <div className="flex justify-end">
          <button
            onClick={handleApproveAll}
            disabled={epicApproveMut.isPending || taskApproveMut.isPending}
            className="rounded bg-green-700 hover:bg-green-800 disabled:opacity-50 text-white text-sm px-4 py-2 font-medium transition-colors"
          >
            Approve All ({total})
          </button>
        </div>
      )}

      {/* Epics section */}
      {data && data.epics.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            Epics ({data.epics.length})
          </h2>
          {data.epics.map((epic) => (
            <EpicRow
              key={epic.epicId}
              epic={epic}
              onApprove={(id) => epicApproveMut.mutate(id)}
              onReject={(id) => epicRejectMut.mutate(id)}
            />
          ))}
        </section>
      )}

      {/* Tasks section */}
      {data && data.tasks.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            Tasks ({data.tasks.length})
          </h2>
          {data.tasks.map((task) => (
            <TaskRow
              key={task.taskId}
              task={task}
              onApprove={(id) => taskApproveMut.mutate(id)}
              onReject={(id) => taskRejectMut.mutate(id)}
            />
          ))}
        </section>
      )}

      <p className="text-center text-xs text-gray-400 pt-4">
        Auto-refreshes every 30 seconds
      </p>
    </div>
  );
}
