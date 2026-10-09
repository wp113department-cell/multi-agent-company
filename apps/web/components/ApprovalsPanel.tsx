"use client";

/**
 * Human Approval UI (Day 13).
 *
 * Pending decisions from plans, questions and protected actions. Questions
 * send the human's answer through the same approval API that resumes the
 * waiting agent; other actions remain yes/no decisions.
 */

import { useCallback, useEffect, useState } from "react";
import { authHeaders, isApprover } from "../lib/auth";

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

// What the agent is waiting for, in plain words.
const ACTION_LABELS: Record<string, string> = {
  plan_review: "Approve the plan",
  git_push: "Send the finished work to GitHub",
  chat_confirmation: "Allow an action",
  clarification: "Answer a question",
  cost_approval: "Approve the cost",
  policy_approval: "Allow a protected change",
};

// Detail keys with a friendlier label (others are shown as written).
const DETAIL_LABELS: Record<string, string> = {
  description: "What",
  details: "Details",
  question: "Question",
  context: "Why",
  options: "Options",
  recommended_option: "Recommended",
  branch: "Branch",
  files_changed: "Files changed",
  subtask_count: "Steps",
};

// Internal flags that mean nothing to a user.
const HIDDEN_DETAILS = new Set(["blocking", "demo"]);

/** A detail value as readable text: lists and objects included. */
function readable(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((v) => (v && typeof v === "object" ? readable(v) : String(v)))
      .join(" · ");
  }
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    const main = o.label ?? o.title ?? o.name ?? o.id ?? o.option;
    const desc = o.description ?? o.text;
    if (main !== undefined) return desc !== undefined ? `${String(main)} (${String(desc)})` : String(main);
    return Object.entries(o)
      .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
      .join(", ");
  }
  return String(value);
}

async function apiFetch<T>(path: string, method = "GET", body?: { answer: string }): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const json = (await res.json()) as T;
  if (!res.ok) {
    const detail = (json as { detail?: string })?.detail ?? `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return json;
}

function DetailsPreview({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(
    ([k, v]) => v !== null && v !== undefined && v !== "" && !HIDDEN_DETAILS.has(k),
  );
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex gap-1">
          <dt className="shrink-0 font-medium text-slate-500 dark:text-slate-500">{DETAIL_LABELS[key] ?? key.replace(/_/g, " ")}:</dt>
          <dd className="line-clamp-3" title={readable(value)}>{readable(value)}</dd>
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
  onApprove: (threadId: string, answer?: string) => void;
  onReject: (threadId: string) => void;
  busy: boolean;
}) {
  const [answer, setAnswer] = useState("");
  const isQuestion = approval.action === "clarification";
  const answerId = `approval-answer-${approval.id}`;
  const options = Array.isArray(approval.details.options)
    ? approval.details.options.filter((option) => option !== null && option !== undefined)
    : [];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-orange-700 dark:text-orange-300">
              {approval.action === "git_push" && approval.details.delivery === "folder"
                ? "Apply the finished work to your folder"
                : (ACTION_LABELS[approval.action] ?? approval.action.replace(/_/g, " "))}
            </span>
            {approval.agentName && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                {approval.agentName}
              </span>
            )}
          </div>
          <h3 className="mt-1.5 text-base font-semibold text-slate-900 dark:text-slate-100">
            {approval.taskId ? (
              <a href={`/tasks/${approval.taskId}`} className="hover:text-orange-700 hover:underline">
                Task #{approval.taskId}
              </a>
            ) : (
              approval.threadId
            )}
          </h3>
          <DetailsPreview details={approval.details} />
        </div>
      </div>

      {approval.status === "pending" ? (
        // Gap-closure Stage 1.4 (answers.md) — UI-level role gating. The
        // server (require_approver) is the real enforcement point; this
        // just stops a viewer-role user from seeing a button that would
        // only 403 (app/middleware/rbac.py's own docstring: "UI hiding
        // buttons is a courtesy only").
        isApprover() ? (
          <form
            className="mt-4 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (busy || (isQuestion && !answer.trim())) return;
              onApprove(approval.threadId, isQuestion ? answer.trim() : undefined);
            }}
          >
            {isQuestion && (
              <div className="space-y-2">
                <label htmlFor={answerId} className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Your answer
                </label>
                <textarea
                  id={answerId}
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  required
                  disabled={busy}
                  rows={3}
                  placeholder="Answer the team's question"
                  className="block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                />
                {options.length > 0 && (
                  <div className="flex flex-wrap gap-2" role="group" aria-label="Suggested answers">
                    {options.map((option, index) => (
                      <button
                        key={index}
                        type="button"
                        disabled={busy}
                        onClick={() => setAnswer(readable(option))}
                        className="rounded-md border border-orange-200 px-2.5 py-1.5 text-xs text-orange-800 hover:bg-orange-50 disabled:opacity-50 dark:border-orange-900 dark:text-orange-300 dark:hover:bg-orange-950"
                      >
                        {readable(option)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={busy || (isQuestion && !answer.trim())}
                className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {isQuestion ? (busy ? "Sending…" : "Send answer") : "Approve"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => onReject(approval.threadId)}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Reject
              </button>
            </div>
          </form>
        ) : (
          <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
            Approver role required to decide on this request.
          </p>
        )
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
            <a
              href={`/tasks/${approval.taskId}`}
              className="text-blue-600 hover:underline dark:text-blue-400"
            >
              View task →
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function ApprovalsPanel() {
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
    // Skip polls while the tab is hidden (audit 09); refresh resumes when it's visible.
    const interval = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const decide = useCallback(
    async (threadId: string, action: "approve" | "reject", answer?: string) => {
      setBusyThreads((prev) => new Set(prev).add(threadId));
      try {
        await apiFetch(
          `/api/approvals/${encodeURIComponent(threadId)}/${action}`,
          "POST",
          action === "approve" && answer ? { answer } : undefined,
        );
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyThreads((prev) => {
          const next = new Set(prev);
          next.delete(threadId);
          return next;
        });
      }
    },
    [refresh],
  );

  const pending = approvals.filter((a) => a.status === "pending");

  return (
    <div className="space-y-10">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Approvals</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Agents pause here before any risky or plan-defining action. Nothing continues until you
          approve or reject below.
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
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
          {pending.map((a) => (
            <ApprovalCard
              key={a.threadId}
              approval={a}
              onApprove={(tid, answer) => void decide(tid, "approve", answer)}
              onReject={(tid) => void decide(tid, "reject")}
              busy={busyThreads.has(a.threadId)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
