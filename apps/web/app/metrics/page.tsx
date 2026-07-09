"use client";

import { useEffect, useState } from "react";
import { fetchSystemMetrics, fetchEpicCosts, SystemMetrics, EpicCostSummary } from "@/lib/api";

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

function pct(rate: number) {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [epicCosts, setEpicCosts] = useState<EpicCostSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSystemMetrics(), fetchEpicCosts()])
      .then(([m, ec]) => {
        setMetrics(m);
        setEpicCosts(ec);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (!metrics) {
    return <p className="text-sm text-slate-400">Loading…</p>;
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Productivity Metrics</h1>
      <p className="mb-6 text-sm text-slate-500">Token usage, cache efficiency, and per-epic cost breakdown.</p>

      {/* Summary cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Total Epics" value={metrics.totalEpics} />
        <StatCard label="Total Agent Runs" value={metrics.totalAgentRuns} />
        <StatCard label="Tokens In" value={fmt(metrics.totalTokensIn)} />
        <StatCard label="Cache Hit Rate" value={pct(metrics.cacheHitRate)} />
      </div>

      {/* Epic status breakdown */}
      {Object.keys(metrics.epicsByStatus).length > 0 && (
        <div className="mb-6 rounded border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Epics by Status</h2>
          <div className="flex flex-wrap gap-3">
            {Object.entries(metrics.epicsByStatus).map(([status, count]) => (
              <span key={status} className="rounded bg-slate-100 px-3 py-1 text-xs">
                <span className="font-medium">{count}</span> {status}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Agent-type breakdown */}
      {metrics.agentTypeBreakdown.length > 0 && (
        <div className="mb-6 rounded border border-slate-200 bg-white shadow-sm">
          <h2 className="px-4 pt-4 text-sm font-semibold text-slate-700">Agent Type Breakdown</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-4 py-2">Agent</th>
                  <th className="px-4 py-2 text-right">Runs</th>
                  <th className="px-4 py-2 text-right">Tokens In</th>
                  <th className="px-4 py-2 text-right">Tokens Out</th>
                  <th className="px-4 py-2 text-right">Cache Read</th>
                  <th className="px-4 py-2 text-right">Cache Hit %</th>
                </tr>
              </thead>
              <tbody>
                {metrics.agentTypeBreakdown.map((a) => (
                  <tr key={a.agentType} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-2 font-medium">{a.agentType}</td>
                    <td className="px-4 py-2 text-right">{a.runCount}</td>
                    <td className="px-4 py-2 text-right">{fmt(a.totalTokensIn)}</td>
                    <td className="px-4 py-2 text-right">{fmt(a.totalTokensOut)}</td>
                    <td className="px-4 py-2 text-right">{fmt(a.totalCacheReadTokens)}</td>
                    <td className="px-4 py-2 text-right">{pct(a.cacheHitRate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Per-epic cost breakdown */}
      {epicCosts.length > 0 && (
        <div className="rounded border border-slate-200 bg-white shadow-sm">
          <h2 className="px-4 pt-4 text-sm font-semibold text-slate-700">Epic Cost Breakdown</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-4 py-2">Epic</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2 text-right">Tokens In</th>
                  <th className="px-4 py-2 text-right">Cache Hit %</th>
                  <th className="px-4 py-2 text-right">Est. Cost</th>
                  <th className="px-4 py-2 text-right">Actual Cost</th>
                </tr>
              </thead>
              <tbody>
                {epicCosts.map((e) => (
                  <tr key={e.epicId} className="border-b border-slate-100 last:border-0">
                    <td className="max-w-xs truncate px-4 py-2">
                      <a href={`/epics/${e.epicId}`} className="text-blue-600 hover:underline">
                        {e.title}
                      </a>
                    </td>
                    <td className="px-4 py-2">{e.status}</td>
                    <td className="px-4 py-2 text-right">{fmt(e.tokensIn)}</td>
                    <td className="px-4 py-2 text-right">{pct(e.cacheHitRate)}</td>
                    <td className="px-4 py-2 text-right">
                      {e.costEstimate != null ? `$${e.costEstimate.toFixed(4)}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {e.costActual != null ? `$${e.costActual.toFixed(4)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {epicCosts.length === 0 && metrics.totalEpics === 0 && (
        <p className="text-sm text-slate-400">No data yet — run some epics first.</p>
      )}
    </div>
  );
}
