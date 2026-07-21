"use client";

/**
 * Fleet Enhancement Dashboard (Day 9).
 *
 * Shows what the 5 self-improvement agents (agent_performance_reviewer,
 * agent_debugger, agent_advisor, knowledge_curator, quality_auditor) found
 * during their autonomous background scans. Nothing happens to your project
 * until you approve a specific request here — approve kicks off that agent's
 * write-capable APPLY phase, streamed live at /stream/[taskId]; reject is final.
 */

import { useCallback, useEffect, useRef, useState } from "react";

interface EnhancementRequest {
  id: number;
  agentName: string;
  title: string;
  description: string;
  category: string;
  priority: "emergency" | "medium" | "low";
  evidence: Record<string, unknown>;
  status: "pending" | "in_progress" | "approved" | "rejected" | "completed" | "failed";
  filesTouched: string[];
  commitSha: string | null;
  restartRequired: boolean;
  error: string | null;
  traceId: string | null;
  createdAt: string;
  decidedAt: string | null;
  decidedBy: string | null;
  completedAt: string | null;
}

const AGENT_LABELS: Record<string, string> = {
  agent_performance_reviewer: "Performance Reviewer",
  agent_debugger: "Debugger",
  agent_advisor: "Advisor",
  knowledge_curator: "Knowledge Curator",
  quality_auditor: "Quality Auditor",
};

const PRIORITY_ORDER: Record<string, number> = { emergency: 0, medium: 1, low: 2 };

const PRIORITY_STYLES: Record<string, string> = {
  emergency: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800",
  medium: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800",
  low: "bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700",
};

const STATUS_STYLES: Record<string, string> = {
  pending: "text-slate-500 dark:text-slate-400",
  in_progress: "text-blue-600 dark:text-blue-400",
  completed: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  rejected: "text-slate-400 dark:text-slate-600",
};

async function apiFetch<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const json = (await res.json()) as T;
  if (!res.ok) {
    const detail = (json as { detail?: string })?.detail ?? `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return json;
}

function PriorityBadge({ priority }: { priority: string }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${PRIORITY_STYLES[priority] ?? PRIORITY_STYLES.low}`}>
      {priority}
    </span>
  );
}

function RequestCard({
  req,
  onApprove,
  onReject,
  busy,
}: {
  req: EnhancementRequest;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {AGENT_LABELS[req.agentName] ?? req.agentName}
            </span>
            <PriorityBadge priority={req.priority} />
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {req.category}
            </span>
          </div>
          <h3 className="mt-1.5 text-base font-semibold text-slate-900 dark:text-slate-100">{req.title}</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{req.description}</p>
        </div>
      </div>

      {req.status === "pending" ? (
        <div className="mt-4 flex gap-2">
          <button
            disabled={busy}
            onClick={() => onApprove(req.id)}
            className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            disabled={busy}
            onClick={() => onReject(req.id)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Reject
          </button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <span className={`font-medium ${STATUS_STYLES[req.status] ?? ""}`}>
            {req.status.replace("_", " ")}
          </span>
          {req.traceId && (req.status === "in_progress" || req.status === "completed" || req.status === "failed") && (
            <a href={`/stream/${req.traceId}`} className="text-blue-600 hover:underline dark:text-blue-400">
              View progress →
            </a>
          )}
          {req.commitSha && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-400">
              {req.commitSha.slice(0, 12)}
            </span>
          )}
          {req.error && <span className="text-red-600 dark:text-red-400">{req.error}</span>}
        </div>
      )}

      {req.status === "completed" && req.restartRequired && (
        <div className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
          Restart the backend/frontend to see this change take effect.
        </div>
      )}
    </div>
  );
}

export default function FleetDashboardPage() {
  const [requests, setRequests] = useState<EnhancementRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const esRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<EnhancementRequest[]>("/api/fleet/requests");
      setRequests(data);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();

    const es = new EventSource("/api/fleet/requests/stream");
    esRef.current = es;
    es.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as { type: string };
        if (event.type === "new_request" || event.type === "status_changed") {
          void refresh();
        }
      } catch {
        // ignore parse errors / pings
      }
    };
    es.onerror = () => {
      // SSE auto-reconnects; nothing to do here
    };

    return () => es.close();
  }, [refresh]);

  const decide = useCallback(
    async (id: number, action: "approve" | "reject") => {
      setBusyIds(prev => new Set(prev).add(id));
      try {
        await apiFetch(`/api/fleet/requests/${id}/${action}`, "POST", {});
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyIds(prev => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [refresh]
  );

  const pending = requests
    .filter(r => r.status === "pending")
    .sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9) || b.createdAt.localeCompare(a.createdAt));
  const active = requests.filter(r => r.status === "in_progress");
  const history = requests
    .filter(r => ["completed", "failed", "rejected"].includes(r.status))
    .slice(0, 20);

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Fleet Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          5 self-improvement agents scan this project in the background. Nothing changes on
          disk until you approve a specific request below.
        </p>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-32 items-center justify-center text-sm text-slate-400">Loading…</div>
      ) : (
        <>
          <section className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Pending Review ({pending.length})
            </h2>
            {pending.length === 0 ? (
              <p className="text-sm text-slate-400 dark:text-slate-500">
                Nothing to review right now — the agents will file a request here when they
                find something real.
              </p>
            ) : (
              <div className="space-y-3">
                {pending.map(r => (
                  <RequestCard
                    key={r.id}
                    req={r}
                    onApprove={id => void decide(id, "approve")}
                    onReject={id => void decide(id, "reject")}
                    busy={busyIds.has(r.id)}
                  />
                ))}
              </div>
            )}
          </section>

          {active.length > 0 && (
            <section className="space-y-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                In Progress ({active.length})
              </h2>
              <div className="space-y-3">
                {active.map(r => (
                  <RequestCard key={r.id} req={r} onApprove={() => {}} onReject={() => {}} busy={false} />
                ))}
              </div>
            </section>
          )}

          {history.length > 0 && (
            <section className="space-y-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                History
              </h2>
              <div className="space-y-3">
                {history.map(r => (
                  <RequestCard key={r.id} req={r} onApprove={() => {}} onReject={() => {}} busy={false} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
