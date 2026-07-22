"use client";

/**
 * Human Approval UI (Day 13).
 *
 * Generic list of every LangGraph thread currently paused at interrupt() —
 * today the only registrant is the planning pipeline's human_review_node
 * (plan_review), reached via POST /tasks/{id}/run. Approve/reject here call
 * the same resume_planning_pipeline() the existing task-detail approve
 * button already uses. Day 14's git-push approval gate will show up here too
 * once it registers into the same pending_approvals table.
 */

import { useCallback, useEffect, useState } from "react";

interface PendingApproval {
  id: number;
  threadId: string;
  taskId: number | null;
  agentName: string;
  action: string;
  details: Record<string, unknown>;
  status: "pending" | "approved" | "rejected";
  createdAt: string;
  decidedAt: string | null;
  decidedBy: string | null;
}

const ACTION_LABELS: Record<string, string> = {
  plan_review: "Plan Review",
  git_push: "Git Push",
};

async function apiFetch<T>(path: string, method = "GET"): Promise<T> {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" } });
  const json = (await res.json()) as T;
  if (!res.ok) {
    const detail = (json as { detail?: string })?.detail ?? `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return json;
}

function DetailsPreview({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex gap-1">
          <dt className="font-medium text-slate-500 dark:text-slate-500">{key}:</dt>
          <dd className="truncate">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ApprovalCard({
  approval,
  onApprove,
  onReject,
  busy,
}: {
  approval: PendingApproval;
  onApprove: (threadId: string) => void;
  onReject: (threadId: string) => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {ACTION_LABELS[approval.action] ?? approval.action}
            </span>
            {approval.agentName && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                {approval.agentName}
              </span>
            )}
          </div>
          <h3 className="mt-1.5 text-base font-semibold text-slate-900 dark:text-slate-100">
            {approval.taskId ? `Task #${approval.taskId}` : approval.threadId}
          </h3>
          <DetailsPreview details={approval.details} />
        </div>
      </div>

      {approval.status === "pending" ? (
        <div className="mt-4 flex gap-2">
          <button
            disabled={busy}
            onClick={() => onApprove(approval.threadId)}
            className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            disabled={busy}
            onClick={() => onReject(approval.threadId)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Reject
          </button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <span
            className={
              approval.status === "approved"
                ? "font-medium text-green-600 dark:text-green-400"
                : "font-medium text-slate-400 dark:text-slate-600"
            }
          >
            {approval.status}
            {approval.decidedBy ? ` by ${approval.decidedBy}` : ""}
          </span>
          {approval.taskId && (
            <a href={`/tasks/${approval.taskId}`} className="text-blue-600 hover:underline dark:text-blue-400">
              View task →
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyThreads, setBusyThreads] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<{ approvals: PendingApproval[] }>("/api/approvals/pending");
      setApprovals(data.approvals);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const decide = useCallback(
    async (threadId: string, action: "approve" | "reject") => {
      setBusyThreads(prev => new Set(prev).add(threadId));
      try {
        await apiFetch(`/api/approvals/${threadId}/${action}`, "POST");
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyThreads(prev => {
          const next = new Set(prev);
          next.delete(threadId);
          return next;
        });
      }
    },
    [refresh]
  );

  const pending = approvals.filter(a => a.status === "pending");

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Approvals</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Agents pause here before any risky or plan-defining action. Nothing continues until you
          approve or reject below.
        </p>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-32 items-center justify-center text-sm text-slate-400">Loading…</div>
      ) : pending.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          Nothing waiting for your approval right now.
        </p>
      ) : (
        <div className="space-y-3">
          {pending.map(a => (
            <ApprovalCard
              key={a.threadId}
              approval={a}
              onApprove={tid => void decide(tid, "approve")}
              onReject={tid => void decide(tid, "reject")}
              busy={busyThreads.has(a.threadId)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
