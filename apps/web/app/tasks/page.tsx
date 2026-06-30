"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { NewTaskForm } from "../../components/NewTaskForm";
import { StatusBadge } from "../../components/StatusBadge";
import { fetchTasks } from "../../lib/api";

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

  const { data: tasks, isLoading } = useQuery({
    queryKey: ["tasks", statusFilter],
    queryFn: () => fetchTasks(statusFilter === "all" ? undefined : statusFilter),
    refetchInterval: 4000, // client-side polling per 15_Mission_Control_Dashboard_Specification.md Stage 1-4
  });

  return (
    <div>
      <NewTaskForm />

      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
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

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        {isLoading && <p className="p-4 text-sm text-slate-500">Loading tasks…</p>}
        {!isLoading && tasks?.length === 0 && (
          <p className="p-4 text-sm text-slate-500">No tasks yet — submit one above.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {tasks?.map((task) => (
            <li key={task.taskId}>
              <Link
                href={`/tasks/${task.taskId}`}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate-50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{task.title}</p>
                  <p className="truncate text-xs text-slate-500">
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
