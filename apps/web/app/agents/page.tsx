"use client";

/**
 * Agent Registry (Mission Control Dashboard Stage 6).
 *
 * Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): GET /api/agents
 * already returned everything this page needs (name/version/capability
 * tags/tool list/success rate/avg retries) — no backend changes required.
 * The gap was purely that no dashboard screen ever consumed it.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAgents, type AgentRegistryEntry } from "@/lib/api";

type SortKey = "name" | "successRate" | "avgRetries";

function pct(rate: number) {
  return `${(rate * 100).toFixed(1)}%`;
}

function SuccessRateBar({ rate }: { rate: number }) {
  const clamped = Math.max(0, Math.min(1, rate));
  const color =
    clamped >= 0.8
      ? "bg-green-500"
      : clamped >= 0.5
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div
          className={`h-1.5 rounded-full ${color} transition-all`}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
      <span className="tabular-nums text-slate-600 dark:text-slate-400">
        {pct(rate)}
      </span>
    </div>
  );
}

export default function AgentRegistryPage() {
  const [tagFilter, setTagFilter] = useState<string>("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDesc, setSortDesc] = useState(false);

  const {
    data: agents,
    isLoading,
    error,
  } = useQuery<AgentRegistryEntry[]>({
    queryKey: ["agents"],
    queryFn: () => fetchAgents(),
    refetchInterval: 30_000,
  });

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    for (const a of agents ?? []) {
      for (const t of a.capabilityTags) tags.add(t);
    }
    return Array.from(tags).sort();
  }, [agents]);

  const rows = useMemo(() => {
    const list = (agents ?? []).filter(
      (a) => !tagFilter || a.capabilityTags.includes(tagFilter)
    );
    const sorted = [...list].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "successRate") cmp = a.successRate - b.successRate;
      else if (sortKey === "avgRetries") cmp = a.avgRetries - b.avgRetries;
      return sortDesc ? -cmp : cmp;
    });
    return sorted;
  }, [agents, tagFilter, sortKey, sortDesc]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDesc((d) => !d);
    } else {
      setSortKey(key);
      setSortDesc(false);
    }
  }

  function SortHeader({ label, sortKeyValue }: { label: string; sortKeyValue: SortKey }) {
    const active = sortKey === sortKeyValue;
    return (
      <th
        className="cursor-pointer select-none px-4 py-3 text-right hover:text-slate-700 dark:hover:text-slate-300"
        onClick={() => toggleSort(sortKeyValue)}
      >
        {label}
        {active && <span className="ml-1">{sortDesc ? "↓" : "↑"}</span>}
      </th>
    );
  }

  const totalAgents = agents?.length ?? 0;
  const avgSuccessRate =
    totalAgents > 0
      ? (agents ?? []).reduce((sum, a) => sum + a.successRate, 0) / totalAgents
      : 0;
  const avgRetries =
    totalAgents > 0
      ? (agents ?? []).reduce((sum, a) => sum + a.avgRetries, 0) / totalAgents
      : 0;

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Agent Registry
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Every registered agent — capabilities, tools, and live success-rate metrics.
        </p>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error instanceof Error ? error.message : "Failed to load agents"}
        </div>
      )}

      {isLoading ? (
        <div className="flex h-32 items-center justify-center text-sm text-slate-400">
          Loading…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Registered agents
              </p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">
                {totalAgents}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Avg success rate
              </p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">
                {pct(avgSuccessRate)}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Avg retries
              </p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">
                {avgRetries.toFixed(2)}
              </p>
            </div>
          </div>

          {allTags.length > 0 && (
            <div className="flex items-center gap-2">
              <label
                htmlFor="tag-filter"
                className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
              >
                Capability
              </label>
              <select
                id="tag-filter"
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-700 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300"
              >
                <option value="">All ({agents?.length ?? 0})</option>
                {allTags.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          )}

          {rows.length === 0 ? (
            <p className="text-sm text-slate-400 dark:text-slate-500">
              No agents registered yet.
            </p>
          ) : (
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 dark:border-slate-800 dark:text-slate-500">
                      <th
                        className="cursor-pointer select-none px-4 py-3 hover:text-slate-700 dark:hover:text-slate-300"
                        onClick={() => toggleSort("name")}
                      >
                        Agent
                        {sortKey === "name" && (
                          <span className="ml-1">{sortDesc ? "↓" : "↑"}</span>
                        )}
                      </th>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Capabilities</th>
                      <th className="px-4 py-3 text-right">Tools</th>
                      <SortHeader label="Success rate" sortKeyValue="successRate" />
                      <SortHeader label="Avg retries" sortKeyValue="avgRetries" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((a) => (
                      <tr
                        key={a.agentId}
                        className="border-b border-slate-50 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                      >
                        <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">
                          {a.name}
                        </td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                          {a.version}
                        </td>
                        <td className="max-w-xs px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {a.capabilityTags.slice(0, 4).map((t) => (
                              <span
                                key={t}
                                className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                              >
                                {t}
                              </span>
                            ))}
                            {a.capabilityTags.length > 4 && (
                              <span className="text-xs text-slate-400 dark:text-slate-500">
                                +{a.capabilityTags.length - 4}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                          {a.toolList.length}
                        </td>
                        <td className="px-4 py-3">
                          <SuccessRateBar rate={a.successRate} />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-600 dark:text-slate-400">
                          {a.avgRetries.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
