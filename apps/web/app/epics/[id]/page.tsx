"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { fetchEpic, approveEpic, rejectEpic, approveCost } from "../../../lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  pending_cost_approval: "bg-yellow-100 text-yellow-800",
  planning: "bg-blue-100 text-blue-800",
  coding: "bg-indigo-100 text-indigo-800",
  ready_for_review: "bg-purple-100 text-purple-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-700",
  halted: "bg-red-200 text-red-800",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export default function EpicDetailPage({ params }: { params: { id: string } }) {
  const epicId = params.id;
  const [userId, setUserId] = useState("approver-1");
  const qc = useQueryClient();

  const { data: epic, isLoading, error } = useQuery({
    queryKey: ["epic", epicId],
    queryFn: () => fetchEpic(epicId),
    refetchInterval: 5000,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["epic", epicId] });

  const approveMutation = useMutation({
    mutationFn: () => approveEpic(epicId, userId),
    onSuccess: invalidate,
  });
  const rejectMutation = useMutation({
    mutationFn: () => rejectEpic(epicId, userId),
    onSuccess: invalidate,
  });
  const approveCostMutation = useMutation({
    mutationFn: () => approveCost(epicId, userId),
    onSuccess: invalidate,
  });

  if (isLoading) return <p className="p-8 text-gray-500">Loading…</p>;
  if (error || !epic)
    return <p className="p-8 text-red-600">Failed to load epic.</p>;

  const canApprove = ["ready_for_review"].includes(epic.status);
  const canReject = ["ready_for_review", "halted", "pending_cost_approval"].includes(epic.status);
  const needsCostApproval = epic.status === "pending_cost_approval";

  return (
    <main className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{epic.title}</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{epicId}</p>
        </div>
        <StatusBadge status={epic.status} />
      </div>

      {/* Description */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Goal</h2>
        <p className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap">{epic.description}</p>
      </section>

      {/* Halt notice */}
      {epic.status === "halted" && epic.haltReason && (
        <div className="rounded-lg border border-red-300 bg-red-50 dark:bg-red-950 dark:border-red-700 p-4">
          <p className="text-sm font-semibold text-red-700 dark:text-red-300">Epic Halted</p>
          <p className="text-sm text-red-600 dark:text-red-400 mt-1">{epic.haltReason}</p>
        </div>
      )}

      {/* Cost summary */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Cost</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500 dark:text-gray-400">Estimate</p>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {epic.costEstimate != null ? `$${epic.costEstimate.toFixed(6)}` : "—"}
            </p>
          </div>
          <div>
            <p className="text-gray-500 dark:text-gray-400">Actual</p>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {epic.costActual != null ? `$${epic.costActual.toFixed(6)}` : "—"}
            </p>
          </div>
        </div>
        {needsCostApproval && (
          <p className="mt-3 text-sm text-yellow-700 dark:text-yellow-300">
            Cost estimate exceeds approval threshold. Approve below to start agents.
          </p>
        )}
      </section>

      {/* Subtasks */}
      {epic.tasks && epic.tasks.length > 0 && (
        <section className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
            Tasks ({epic.tasks.length})
          </h2>
          <div className="space-y-2">
            {epic.tasks.map((task) => (
              <div
                key={task.taskId}
                className="flex items-center justify-between rounded border border-gray-100 dark:border-gray-700 px-3 py-2"
              >
                <span className="text-sm text-gray-800 dark:text-gray-200">{task.title}</span>
                <StatusBadge status={task.status} />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Approval actions */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800 space-y-4">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Actions</h2>

        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-500 dark:text-gray-400 shrink-0">Your User ID:</label>
          <input
            className="rounded border border-gray-300 dark:border-gray-600 px-2 py-1 text-xs w-40 dark:bg-gray-700 dark:text-gray-100"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          />
        </div>

        {needsCostApproval && (
          <button
            onClick={() => approveCostMutation.mutate()}
            disabled={approveCostMutation.isPending}
            className="rounded bg-yellow-500 px-4 py-2 text-sm font-medium text-white hover:bg-yellow-600 disabled:opacity-50"
          >
            {approveCostMutation.isPending ? "Approving…" : "Approve Cost & Start Agents"}
          </button>
        )}

        <div className="flex gap-3">
          {canApprove && (
            <button
              onClick={() => approveMutation.mutate()}
              disabled={approveMutation.isPending}
              className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {approveMutation.isPending ? "Approving…" : "Approve Epic"}
            </button>
          )}
          {canReject && (
            <button
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              className="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {rejectMutation.isPending ? "Rejecting…" : "Reject Epic"}
            </button>
          )}
        </div>

        {(approveMutation.isError || rejectMutation.isError || approveCostMutation.isError) && (
          <p className="text-sm text-red-600">
            {(
              (approveMutation.error || rejectMutation.error || approveCostMutation.error) as Error
            )?.message}
          </p>
        )}
      </section>

      <p className="text-xs text-gray-400">
        Created {new Date(epic.createdAt).toLocaleString()}
        {epic.updatedAt && ` · Updated ${new Date(epic.updatedAt).toLocaleString()}`}
      </p>
    </main>
  );
}
