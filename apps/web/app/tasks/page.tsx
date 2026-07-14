"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { NewTaskForm } from "../../components/NewTaskForm";
import { StatusBadge } from "../../components/StatusBadge";
import { fetchTasks, listRepos, type RepoRecord } from "../../lib/api";

const STATUS_FILTERS = [
  "all",
  "pending",
  "planning",
  "ready_for_review",
  "coding",
  "testing",
  "blocked",
  "completed",
  "failed",
] as const;

export default function TaskListPage() {
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("all");
  const [repoFilter, setRepoFilter] = useState<number | null>(null);

  const { data: reposData } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    staleTime: 30_000,
  });

  const readyRepos: RepoRecord[] = (reposData?.repos ?? []).filter((r) => r.status === "ready");

  const { data: tasks, isLoading } = useQuery({
    queryKey: ["tasks", statusFilter, repoFilter],
    queryFn: () => fetchTasks(statusFilter === "all" ? undefined : statusFilter, repoFilter),
    refetchInterval: 4000,
  });

  return (
    <div>
      <NewTaskForm />

      {/* Status filter chips */}
      <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium ${
              statusFilter === s
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200"
            }`}
          >
            {s.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {/* Repo filter — only shown when there are cloned repos */}
      {readyRepos.length > 0 && (
        <div className="mb-3 flex items-center gap-2">
          <span className="text-xs text-slate-500">Repo:</span>
          <button
            onClick={() => setRepoFilter(null)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              repoFilter === null
                ? "bg-indigo-600 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200"
            }`}
          >
            All
          </button>
          {readyRepos.map((repo) => (
            <button
              key={repo.id}
              onClick={() => setRepoFilter(repo.id)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                repoFilter === repo.id
                  ? "bg-indigo-600 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200"
              }`}
            >
              {repo.name}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        {isLoading && <p className="p-4 text-sm text-slate-500">Loading tasks…</p>}
        {!isLoading && tasks?.length === 0 && (
          <p className="p-4 text-sm text-slate-500">
            No tasks{repoFilter !== null ? " for this repo" : ""}
            {statusFilter !== "all" ? ` with status "${statusFilter.replace(/_/g, " ")}"` : ""}.
          </p>
        )}
        <ul className="divide-y divide-slate-100">
          {tasks?.map((task) => (
            <li key={task.id}>
              <Link
                href={`/tasks/${task.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate-50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{task.title}</p>
                  <p className="truncate text-xs text-slate-500">
                    {task.repoName ? (
                      <span className="mr-1 rounded bg-slate-100 px-1 py-0.5 font-mono text-slate-600">
                        {task.repoName}
                      </span>
                    ) : null}
                    {task.project ?? "no project"} · {task.priority} priority
                  </p>
                </div>
                <StatusBadge status={task.status} />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
