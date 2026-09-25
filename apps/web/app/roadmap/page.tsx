"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchRoadmap,
  listRepos,
  updateRoadmapItemStatus,
  type RepoRecord,
  type RoadmapItem,
} from "../../lib/api";

// #498/#484 (2026-09-24, "Roadmap tracked, sequenced, and re-sequenced
// against real progress") — GET /api/roadmap and PATCH
// /api/roadmap/items/{id}/status existed with zero frontend consumer until
// now. Read-only display + the one real write the backend actually
// supports (marking an item's status, which the next roadmap_agent run for
// this repo reads back to genuinely re-sequence around) — no "generate a
// roadmap" button here, since triggering roadmap_agent requires an
// existing DevTask id (POST /api/specialized-agents/roadmap_agent/run),
// not a bare repo — out of scope for surfacing an already-built read/write
// API, not silently dropped.

const STATUS_OPTIONS = ["planned", "in_progress", "completed", "superseded"] as const;

function StatusPill({ status }: { status: string }) {
  const styles: Record<string, string> = {
    planned: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
    in_progress: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
    completed: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300",
    superseded: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? styles.planned}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function RoadmapItemRow({
  item,
  onStatusChange,
}: {
  item: RoadmapItem;
  onStatusChange: (id: number, status: string) => void;
}) {
  return (
    <tr className="border-b border-slate-50 last:border-0 dark:border-slate-800">
      <td className="px-4 py-3 text-right tabular-nums text-slate-400">{item.sequenceOrder}</td>
      <td className="px-4 py-3 text-xs text-slate-500">{item.phase}</td>
      <td className="max-w-md px-4 py-3 text-sm text-slate-800 dark:text-slate-200">
        {item.initiative}
        {item.dependencies.length > 0 && (
          <p className="mt-1 text-xs text-slate-400">
            depends on: {item.dependencies.join(", ")}
          </p>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-slate-500">{item.impact}</td>
      <td className="px-4 py-3 text-xs text-slate-500">{item.effort}</td>
      <td className="px-4 py-3 text-xs text-slate-500">{item.confidence}</td>
      <td className="px-4 py-3">
        <select
          value={item.status}
          onChange={(e) => onStatusChange(item.id, e.target.value)}
          className="rounded-lg border border-slate-200 bg-transparent px-2 py-1 text-xs dark:border-slate-700"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-3">
        <StatusPill status={item.status} />
      </td>
    </tr>
  );
}

export default function RoadmapPage() {
  const qc = useQueryClient();
  const [selectedRepo, setSelectedRepo] = useState<number | null>(null);

  const { data: reposData } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    staleTime: 30_000,
  });
  const readyRepos: RepoRecord[] = (reposData?.repos ?? []).filter((r) => r.status === "ready");
  const repoId = selectedRepo ?? readyRepos[0]?.id ?? null;

  const { data: roadmap, isLoading } = useQuery({
    queryKey: ["roadmap", repoId],
    queryFn: () => fetchRoadmap(repoId as number),
    enabled: repoId !== null,
    refetchInterval: 30_000,
  });

  async function handleStatusChange(itemId: number, status: string) {
    await updateRoadmapItemStatus(itemId, status);
    void qc.invalidateQueries({ queryKey: ["roadmap", repoId] });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Roadmap</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            The latest tracked roadmap for a repository, sequenced by the roadmap agent.
          </p>
        </div>
        {readyRepos.length > 0 && (
          <select
            value={repoId ?? ""}
            onChange={(e) => setSelectedRepo(Number(e.target.value))}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800"
          >
            {readyRepos.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {repoId === null ? (
        <p className="text-sm text-slate-400">No ready repositories yet.</p>
      ) : isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : !roadmap ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No roadmap has been generated for this repository yet. One appears here once the
            roadmap agent has run against it.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {roadmap.summary && (
            <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-300">
              {roadmap.summary}
            </p>
          )}
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-slate-800 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                    <th className="px-4 py-3 text-right">#</th>
                    <th className="px-4 py-3">Phase</th>
                    <th className="px-4 py-3">Initiative</th>
                    <th className="px-4 py-3">Impact</th>
                    <th className="px-4 py-3">Effort</th>
                    <th className="px-4 py-3">Confidence</th>
                    <th className="px-4 py-3">Set status</th>
                    <th className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {[...roadmap.items]
                    .sort((a, b) => a.sequenceOrder - b.sequenceOrder)
                    .map((item) => (
                      <RoadmapItemRow key={item.id} item={item} onStatusChange={handleStatusChange} />
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
