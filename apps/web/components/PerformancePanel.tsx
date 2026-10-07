"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { authHeaders } from "../lib/auth";
import { Icon } from "./Icon";

interface Summary {
  tasks: {
    total: number;
    completed: number;
    failed: number;
    inProgress: number;
    waitingForYou: number;
    blocked: number;
    successRate: number | null;
    avgMinutesToComplete: number | null;
  };
  cost: { spentTodayUsd: number; dailyBudgetUsd: number | null; spent30dUsd: number; agentRuns30d: number };
  busiestAgents: { agentName: string; runs: number }[];
}

async function fetchSummary(): Promise<Summary> {
  const res = await fetch("/api/fleet/reports/summary", { headers: authHeaders() });
  if (!res.ok) throw new Error(`Could not load performance (${res.status})`);
  return (await res.json()) as Summary;
}

function duration(min: number | null): string {
  if (min == null) return "—";
  if (min < 60) return `${Math.round(min)} min`;
  const h = min / 60;
  return h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`;
}

const SPECIAL: Record<string, string> = { qa: "QA", pm: "PM", ai: "AI", api: "API", sql: "SQL", ux: "UX", devops: "DevOps" };

function label(name: string): string {
  return name
    .replace(/_agent$/, "")
    .split("_")
    .map((w) => SPECIAL[w] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function Stat({ icon, label: l, value, hint }: { icon: string; label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-soft dark:border-slate-700 dark:bg-slate-900">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <Icon name={icon} size={14} className="text-orange-600" /> {l}
      </p>
      <p className="mt-2 text-2xl font-extrabold text-slate-900 dark:text-white">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** KPIs at a glance: task results, speed, and AI cost against the budget. */
export function PerformancePanel() {
  const { data, isLoading, error } = useQuery({ queryKey: ["perf-summary"], queryFn: fetchSummary, refetchInterval: 30000 });
  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error || !data)
    return <p className="text-sm text-red-600">{error instanceof Error ? error.message : "Could not load performance"}</p>;
  const { tasks, cost } = data;
  const pct = cost.dailyBudgetUsd ? Math.min(100, (cost.spentTodayUsd / cost.dailyBudgetUsd) * 100) : 0;
  const maxRuns = Math.max(1, ...data.busiestAgents.map((a) => a.runs));

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon="check-circle" label="Tasks completed" value={String(tasks.completed)} hint={`${tasks.total} tasks in total`} />
        <Stat
          icon="target"
          label="Success rate"
          value={tasks.successRate == null ? "—" : `${Math.round(tasks.successRate * 100)}%`}
          hint={`${tasks.failed} failed`}
        />
        <Stat icon="trending-up" label="Average time to finish" value={duration(tasks.avgMinutesToComplete)} />
        <Stat
          icon="hand"
          label="Waiting for you"
          value={String(tasks.waitingForYou)}
          hint={`${tasks.inProgress} in progress · ${tasks.blocked} blocked`}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-700 dark:bg-slate-900">
          <h3 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
            <Icon name="coins" size={16} className="text-orange-600" /> AI cost
          </h3>
          <p className="mt-3 text-3xl font-extrabold text-slate-900 dark:text-white">
            ${cost.spentTodayUsd.toFixed(2)}
            <span className="ml-1 text-base font-medium text-slate-500">
              {cost.dailyBudgetUsd ? `of $${cost.dailyBudgetUsd.toFixed(2)} today` : "today"}
            </span>
          </p>
          {cost.dailyBudgetUsd && (
            <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-orange-100 dark:bg-slate-800" aria-hidden="true">
              <div
                className={`h-full rounded-full ${pct > 85 ? "bg-red-500" : "bg-gradient-to-r from-orange-400 to-orange-600"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          )}
          <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
            Last 30 days: <strong>${cost.spent30dUsd.toFixed(2)}</strong> across {cost.agentRuns30d} agent runs.
          </p>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-700 dark:bg-slate-900">
          <h3 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
            <Icon name="bot" size={16} className="text-orange-600" /> Busiest agents (30 days)
          </h3>
          {data.busiestAgents.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No agent work yet.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {data.busiestAgents.map((a) => (
                <li key={a.agentName} className="text-sm">
                  <div className="flex justify-between text-slate-700 dark:text-slate-300">
                    <span>{label(a.agentName)}</span>
                    <span className="tabular-nums text-slate-500">{a.runs} runs</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className="h-full rounded-full bg-orange-500" style={{ width: `${(a.runs / maxRuns) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <Link
        href="/metrics"
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-orange-700 hover:text-orange-800 dark:text-orange-300"
      >
        Open the detailed dashboard (tokens, cache, cost per agent and epic) <Icon name="arrow-right" size={14} />
      </Link>
    </div>
  );
}
