"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchSystemMetrics,
  fetchEpicCosts,
  type SystemMetrics,
  type EpicCostSummary,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Pricing constants (Sonnet as primary model; Haiku for router)
// Blended approximate: ~80% Sonnet, ~20% Haiku calls
// ---------------------------------------------------------------------------
const IN_PER_1M = 2.5;          // ~$2.5/M blended input
const OUT_PER_1M = 12.0;        // ~$12/M blended output
const CACHE_READ_PER_1M = 0.25; // cache reads at ~10% of input

function costIn(tokens: number) { return (tokens / 1_000_000) * IN_PER_1M; }
function costOut(tokens: number) { return (tokens / 1_000_000) * OUT_PER_1M; }
function costCacheRead(tokens: number) { return (tokens / 1_000_000) * CACHE_READ_PER_1M; }

function totalCost(m: SystemMetrics): number {
  return (
    costIn(m.totalTokensIn) +
    costOut(m.totalTokensOut) +
    costCacheRead(m.totalCacheReadTokens)
  );
}

function cacheSavings(m: SystemMetrics): number {
  // what we would have paid if cache reads were full input price
  return (m.totalCacheReadTokens / 1_000_000) * (IN_PER_1M - CACHE_READ_PER_1M);
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function usd(n: number) {
  if (n === 0) return "$0.00";
  if (n < 0.001) return `<$0.001`;
  return `$${n.toFixed(4)}`;
}

function pct(rate: number) {
  return `${(rate * 100).toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "blue" | "amber" | "slate";
}) {
  const accentClass =
    accent === "green" ? "text-green-700 dark:text-green-400"
    : accent === "blue" ? "text-blue-700 dark:text-blue-400"
    : accent === "amber" ? "text-amber-700 dark:text-amber-400"
    : "text-slate-900 dark:text-slate-100";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className={`mt-1.5 text-2xl font-bold tabular-nums ${accentClass}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{sub}</p>}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
      {children}
    </h2>
  );
}

function Bar({ value, max, color = "bg-blue-500" }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
      <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function StatusPill({ status, count }: { status: string; count: number }) {
  const colors: Record<string, string> = {
    completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
    in_progress: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
    planning: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
    pending: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    blocked: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
    approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    rejected: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  };
  const cls = colors[status] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${cls}`}>
      <span className="text-sm font-bold">{count}</span>
      {status.replace("_", " ")}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function KpisPage() {
  const { data: metrics, isLoading: loadingMetrics, error: errMetrics } = useQuery<SystemMetrics>({
    queryKey: ["system-metrics"],
    queryFn: fetchSystemMetrics,
    refetchInterval: 30_000,
  });

  const { data: epicCosts, isLoading: loadingEpics } = useQuery<EpicCostSummary[]>({
    queryKey: ["epic-costs"],
    queryFn: fetchEpicCosts,
    refetchInterval: 30_000,
  });

  if (loadingMetrics) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-slate-400">
        Loading…
      </div>
    );
  }

  if (errMetrics) {
    return (
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
        {errMetrics instanceof Error ? errMetrics.message : "Failed to load metrics"}
      </div>
    );
  }

  if (!metrics) return null;

  const totalSpend = totalCost(metrics);
  const savings = cacheSavings(metrics);
  const avgTokensPerRun = metrics.totalAgentRuns > 0
    ? Math.round((metrics.totalTokensIn + metrics.totalTokensOut) / metrics.totalAgentRuns)
    : 0;

  const epics = epicCosts ?? [];
  const sortedAgents = [...metrics.agentTypeBreakdown].sort((a, b) => b.runCount - a.runCount);
  const maxAgentRuns = sortedAgents[0]?.runCount ?? 1;

  return (
    <div className="space-y-10">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">KPIs</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Cost, performance, and productivity across all agents and epics.
        </p>
      </div>

      {/* ── Section 1: Cost KPIs ─────────────────────────────── */}
      <section className="space-y-4">
        <SectionHeader>Cost</SectionHeader>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <KpiCard
            label="Total estimated spend"
            value={usd(totalSpend)}
            sub="blended Sonnet+Haiku rate"
            accent="slate"
          />
          <KpiCard
            label="Cache savings"
            value={usd(savings)}
            sub={`${pct(metrics.cacheHitRate)} cache hit rate`}
            accent="green"
          />
          <KpiCard
            label="Tokens in"
            value={fmt(metrics.totalTokensIn)}
            sub={usd(costIn(metrics.totalTokensIn))}
          />
          <KpiCard
            label="Tokens out"
            value={fmt(metrics.totalTokensOut)}
            sub={usd(costOut(metrics.totalTokensOut))}
          />
        </div>
      </section>

      {/* ── Section 2: Performance KPIs ───────────────────────── */}
      <section className="space-y-4">
        <SectionHeader>Performance</SectionHeader>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <KpiCard
            label="Total epics"
            value={String(metrics.totalEpics)}
            accent="blue"
          />
          <KpiCard
            label="Agent runs"
            value={fmt(metrics.totalAgentRuns)}
            sub={`${pct(metrics.cacheHitRate)} cache efficiency`}
          />
          <KpiCard
            label="Avg tokens / run"
            value={fmt(avgTokensPerRun)}
            sub="in + out combined"
          />
          <KpiCard
            label="Cache reads"
            value={fmt(metrics.totalCacheReadTokens)}
            sub={usd(costCacheRead(metrics.totalCacheReadTokens))}
            accent="green"
          />
        </div>
      </section>

      {/* ── Section 3: Epic status breakdown ──────────────────── */}
      {Object.keys(metrics.epicsByStatus).length > 0 && (
        <section className="space-y-3">
          <SectionHeader>Epics by status</SectionHeader>
          <div className="flex flex-wrap gap-2">
            {Object.entries(metrics.epicsByStatus).map(([status, count]) => (
              <StatusPill key={status} status={status} count={count} />
            ))}
          </div>
        </section>
      )}

      {/* ── Section 4: Agent breakdown ────────────────────────── */}
      <section className="space-y-3">
        <SectionHeader>Agent breakdown</SectionHeader>
        {sortedAgents.length === 0 ? (
          <p className="text-sm text-slate-400 dark:text-slate-500">No agent runs recorded yet.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-slate-800 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                    <th className="px-4 py-3">Agent</th>
                    <th className="px-4 py-3 text-right">Runs</th>
                    <th className="px-4 py-3 text-right">Tokens in</th>
                    <th className="px-4 py-3 text-right">Tokens out</th>
                    <th className="px-4 py-3 text-right">Cache hit</th>
                    <th className="px-4 py-3 text-right">Est. cost</th>
                    <th className="w-24 px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedAgents.map((a) => {
                    const agentCost = costIn(a.totalTokensIn) + costOut(a.totalTokensOut) + costCacheRead(a.totalCacheReadTokens);
                    return (
                      <tr key={a.agentType} className="border-b border-slate-50 last:border-0 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                        <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">{a.agentType}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">{a.runCount}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">{fmt(a.totalTokensIn)}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">{fmt(a.totalTokensOut)}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">{pct(a.cacheHitRate)}</td>
                        <td className="px-4 py-3 text-right tabular-nums font-medium text-slate-800 dark:text-slate-200">{usd(agentCost)}</td>
                        <td className="px-4 py-3">
                          <Bar value={a.runCount} max={maxAgentRuns} color="bg-blue-400" />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* ── Section 5: Per-epic cost ──────────────────────────── */}
      <section className="space-y-3">
        <SectionHeader>Cost by epic</SectionHeader>
        {loadingEpics ? (
          <p className="text-sm text-slate-400 dark:text-slate-500">Loading…</p>
        ) : epics.length === 0 ? (
          <p className="text-sm text-slate-400 dark:text-slate-500">No epics yet.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-slate-800 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                    <th className="px-4 py-3">Epic</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Tokens in</th>
                    <th className="px-4 py-3 text-right">Cache hit</th>
                    <th className="px-4 py-3 text-right">Est. cost</th>
                    <th className="px-4 py-3 text-right">Actual cost</th>
                  </tr>
                </thead>
                <tbody>
                  {epics.map((e) => {
                    const derived = costIn(e.tokensIn) + costOut(e.tokensOut) + costCacheRead(e.cacheReadTokens);
                    return (
                      <tr key={e.epicId} className="border-b border-slate-50 last:border-0 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                        <td className="max-w-xs truncate px-4 py-3">
                          <a href={`/epics/${e.epicId}`} className="text-blue-600 hover:underline dark:text-blue-400">{e.title}</a>
                        </td>
                        <td className="px-4 py-3">
                          <StatusPill status={e.status} count={0} />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">{fmt(e.tokensIn)}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">{pct(e.cacheHitRate)}</td>
                        <td className="px-4 py-3 text-right tabular-nums font-medium text-slate-800 dark:text-slate-200">
                          {e.costEstimate != null ? usd(e.costEstimate) : usd(derived)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                          {e.costActual != null ? usd(e.costActual) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <p className="text-xs text-slate-400 dark:text-slate-600">
        Cost estimates use blended pricing: ~$2.5/M input, ~$12/M output, ~$0.25/M cache reads.
        Cache hit rate shows what % of input tokens were served from the prompt cache.
      </p>
    </div>
  );
}
