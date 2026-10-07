"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { authHeaders } from "../lib/auth";

interface NotificationItem {
  taskId: number;
  title: string;
  status: string;
  blockedReason: string | null;
  message: string;
  at: string;
}

async function fetchNotifications(): Promise<NotificationItem[]> {
  const res = await fetch("/api/notifications?days=30&limit=100", { headers: authHeaders() });
  if (!res.ok) throw new Error(`Could not load notifications (${res.status})`);
  return ((await res.json()) as { items: NotificationItem[] }).items;
}

/** Tasks that got stuck or failed recently (same feed as the bell icon). */
export function NotificationsPanel() {
  const { data = [], isLoading, error } = useQuery({
    queryKey: ["notifications-panel"],
    queryFn: fetchNotifications,
    refetchInterval: 15000,
  });
  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error instanceof Error ? error.message : "Error"}</p>;
  if (data.length === 0)
    return (
      <p className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
        All clear. No task got stuck or failed in the last 30 days.
      </p>
    );
  return (
    <ul className="space-y-2">
      {data.map((n) => (
        <li key={`${n.taskId}-${n.at}`}>
          <Link
            href={`/tasks/${n.taskId}`}
            className="flex flex-col gap-1 rounded-2xl border border-slate-200 bg-white p-4 shadow-soft transition hover:border-orange-200 sm:flex-row sm:items-center sm:justify-between dark:border-slate-700 dark:bg-slate-900"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold text-slate-900 dark:text-white">{n.title}</span>
              <span className="block text-sm text-slate-600 dark:text-slate-400">{n.message}</span>
            </span>
            <span className="flex shrink-0 items-center gap-2 text-xs">
              <span
                className={`rounded-full px-2 py-0.5 font-semibold ${
                  n.status === "failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800"
                }`}
              >
                {n.status === "failed" ? "Failed" : "Blocked"}
              </span>
              <span className="text-slate-400">{new Date(n.at).toLocaleString()}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
