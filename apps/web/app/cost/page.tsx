"use client";

import { useEffect, useState } from "react";

interface SystemMetrics {
  total_tasks: number;
  completed_tasks: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  agents: AgentMetric[];
}

interface AgentMetric {
  agent: string;
  total_tasks: number;
  total_tokens_in: number;
  total_tokens_out: number;
}

interface EpicCost {
  epic_id: number;
  title: string;
  tokens_in: number;
  tokens_out: number;
  cost_estimate: number | null;
}

// Haiku pricing (cheapest tier); adjust if your config uses Sonnet/Opus
const COST_PER_1K_IN = 0.00025;
const COST_PER_1K_OUT = 0.00125;

function estimateCost(tokensIn: number, tokensOut: number): number {
  return (tokensIn / 1000) * COST_PER_1K_IN + (tokensOut / 1000) * COST_PER_1K_OUT;
}

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function usd(n: number) {
  return `$${n.toFixed(4)}`;
}

function Bar({ pct, color = "bg-blue-500" }: { pct: number; color?: string }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
      <div
        className={`h-2 rounded-full ${color} transition-all`}
        style={{ width: `${Math.min(100, pct)}%` }}
      />
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-slate-100">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

export default function CostPage() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [epics, setEpics] = useState<EpicCost[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch("/api/metrics").then((r) => r.json()),
      fetch("/api/metrics/epics").then((r) => r.json()),
    ])
      .then(([m, e]) => {
        setMetrics(m);
        setEpics(Array.isArray(e) ? e : []);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-slate-400">
        Loading cost data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
        Error: {error}
      </div>
    );
  }

  if (!metrics) return null;

  const totalEstimate = estimateCost(metrics.total_tokens_in, metrics.total_tokens_out);
  const sortedAgents = [...(metrics.agents ?? [])].sort(
    (a, b) =>
      estimateCost(b.total_tokens_in, b.total_tokens_out) -
      estimateCost(a.total_tokens_in, a.total_tokens_out)
  );
  const maxAgentCost = sortedAgents.length
    ? estimateCost(
        sortedAgents[0].total_tokens_in,
        sortedAgents[0].total_tokens_out
      )
    : 1;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Cost Dashboard
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Token consumption and cost estimates across all agents and tasks.
        </p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard
          label="Total tokens in"
          value={fmt(metrics.total_tokens_in)}
          sub={usd((metrics.total_tokens_in / 1000) * COST_PER_1K_IN)}
        />
        <StatCard
          label="Total tokens out"
          value={fmt(metrics.total_tokens_out)}
          sub={usd((metrics.total_tokens_out / 1000) * COST_PER_1K_OUT)}
        />
        <StatCard
          label="Estimated total cost"
          value={usd(totalEstimate)}
          sub={`${metrics.total_tasks} tasks`}
        />
        <StatCard
          label="Cost per task"
          value={metrics.total_tasks > 0 ? usd(totalEstimate / metrics.total_tasks) : "$0.00"}
          sub={`${metrics.completed_tasks} completed`}
        />
      </div>

      {/* Per-agent breakdown */}
      {sortedAgents.length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
            Cost by Agent
          </h2>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 dark:border-slate-800">
                  <th className="px-4 py-3 text-left font-medium text-slate-500 dark:text-slate-400">Agent</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Tasks</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Tokens in</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Tokens out</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Est. cost</th>
                  <th className="w-32 px-4 py-3 text-slate-500 dark:text-slate-400"></th>
                </tr>
              </thead>
              <tbody>
                {sortedAgents.map((a) => {
                  const cost = estimateCost(a.total_tokens_in, a.total_tokens_out);
                  const pct = maxAgentCost > 0 ? (cost / maxAgentCost) * 100 : 0;
                  return (
                    <tr key={a.agent} className="border-b border-slate-50 last:border-0 dark:border-slate-800">
                      <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">
                        {a.agent}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                        {a.total_tasks}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                        {fmt(a.total_tokens_in)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                        {fmt(a.total_tokens_out)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium text-slate-800 dark:text-slate-200">
                        {usd(cost)}
                      </td>
                      <td className="px-4 py-3">
                        <Bar pct={pct} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Per-epic cost */}
      {epics.length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
            Cost by Epic
          </h2>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 dark:border-slate-800">
                  <th className="px-4 py-3 text-left font-medium text-slate-500 dark:text-slate-400">Epic</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Tokens in</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Tokens out</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-500 dark:text-slate-400">Est. cost</th>
                </tr>
              </thead>
              <tbody>
                {epics.map((ep) => {
                  const cost = ep.cost_estimate ?? estimateCost(ep.tokens_in, ep.tokens_out);
                  return (
                    <tr key={ep.epic_id} className="border-b border-slate-50 last:border-0 dark:border-slate-800">
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{ep.title}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                        {fmt(ep.tokens_in)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                        {fmt(ep.tokens_out)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium text-slate-800 dark:text-slate-200">
                        {usd(cost)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="text-xs text-slate-400 dark:text-slate-600">
        Cost estimates use Haiku pricing ($0.25/M input, $1.25/M output). Adjust constants in
        this file to match your model tier.
      </p>
    </div>
  );
}
