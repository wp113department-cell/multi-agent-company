"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { StatusBadge } from "../../../components/StatusBadge";
import { fetchTask } from "../../../lib/api";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: task, isLoading, error } = useQuery({
    queryKey: ["task", params.id],
    queryFn: () => fetchTask(params.id),
    refetchInterval: 3000,
  });

  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{(error as Error).message}</p>;
  if (!task) return null;

  return (
    <div className="space-y-6">
      <Link href="/tasks" className="text-sm text-slate-500 hover:underline">
        ← All tasks
      </Link>

      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-2 flex items-center justify-between">
          <h1 className="text-lg font-semibold">{task.title}</h1>
          <StatusBadge status={task.status} />
        </div>
        <p className="mb-3 text-sm text-slate-500">
          {task.project ?? "no project"} · {task.priority} priority · assigned to{" "}
          {task.assignedAgent ?? "unassigned"}
        </p>
        {task.description && <p className="text-sm text-slate-700">{task.description}</p>}
      </div>

      {task.plan && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Agent-generated plan</h2>
          <pre className="whitespace-pre-wrap text-sm text-slate-800">{task.plan}</pre>
        </div>
      )}

      {task.filesTouched.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Files touched</h2>
          <ul className="list-inside list-disc text-sm text-slate-700">
            {task.filesTouched.map((f) => (
              <li key={f} className="font-mono text-xs">
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}

      {task.finalSummary && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Final summary</h2>
          <p className="text-sm text-slate-700">{task.finalSummary}</p>
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Log timeline</h2>
        {task.logs.length === 0 && <p className="text-sm text-slate-500">No log entries yet.</p>}
        <ol className="space-y-3">
          {task.logs.map((log) => (
            <li key={log.logId} className="border-l-2 border-slate-200 pl-3">
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <span className="font-mono uppercase">{log.category}</span>
                <span>{new Date(log.createdAt).toLocaleString()}</span>
              </div>
              <p className="text-sm text-slate-800">{log.message}</p>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
