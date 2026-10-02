"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { authHeaders } from "../lib/auth";

/**
 * In-app failure alerts (production audit 08, owner's choice over a
 * Slack/Discord webhook). Shows tasks that became blocked or failed in the
 * last 7 days (GET /api/notifications). Unread = newer than the last time
 * this browser opened the list; a short toast appears when a new one arrives
 * while the app is open.
 */

export interface TaskNotification {
  taskId: number;
  title: string;
  status: string;
  blockedReason: string | null;
  message: string;
  at: string;
}

const SEEN_KEY = "gridiron_notifications_seen_at";
const POLL_MS = 15_000;

function readSeen(): string {
  try {
    return window.localStorage.getItem(SEEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeSeen(value: string): void {
  try {
    window.localStorage.setItem(SEEN_KEY, value);
  } catch {
    // storage unavailable (private window) — unread count just resets
  }
}

export function NotificationBell({ authed }: { authed: boolean }) {
  const [items, setItems] = useState<TaskNotification[]>([]);
  const [seenAt, setSeenAt] = useState("");
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<TaskNotification | null>(null);
  const known = useRef<Set<string> | null>(null);

  useEffect(() => setSeenAt(readSeen()), []);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/notifications", { headers: authHeaders() });
      if (!res.ok) return;
      const data = (await res.json()) as { items: TaskNotification[] };
      const keys = new Set(data.items.map((i) => `${i.taskId}@${i.at}`));
      if (known.current !== null) {
        const fresh = data.items.find((i) => !known.current!.has(`${i.taskId}@${i.at}`));
        if (fresh) setToast(fresh);
      }
      known.current = keys;
      setItems(data.items);
    } catch {
      // non-fatal — the bell keeps its last known state
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    void refresh();
    const interval = setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_MS);
    return () => clearInterval(interval);
  }, [authed, refresh]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  if (!authed) return null;

  const unread = items.filter((i) => !seenAt || i.at > seenAt).length;

  function toggle() {
    const next = !open;
    setOpen(next);
    const newest = items[0]?.at;
    if (next && newest) {
      setSeenAt(newest);
      writeSeen(newest);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={toggle}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        className="relative rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Task alerts"
          className="absolute right-0 z-50 mt-2 w-80 rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <div className="border-b border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">
            Blocked or failed tasks (last 7 days)
          </div>
          {items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">No alerts.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.map((i) => (
                <li
                  key={`${i.taskId}@${i.at}`}
                  className="border-b border-slate-100 last:border-0 dark:border-slate-800"
                >
                  <Link
                    href={`/tasks/${i.taskId}`}
                    onClick={() => setOpen(false)}
                    className="block px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <span className="flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          i.status === "failed"
                            ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                            : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                        }`}
                      >
                        {i.status}
                      </span>
                      <span className="truncate">{i.title}</span>
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-slate-500 dark:text-slate-400">
                      {i.message}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 right-4 z-50 w-80 rounded-md border border-red-200 bg-white p-3 shadow-lg dark:border-red-900 dark:bg-slate-900"
        >
          <p className="text-sm font-semibold text-red-700 dark:text-red-300">
            Task {toast.status}: {toast.title}
          </p>
          <p className="mt-1 truncate text-xs text-slate-600 dark:text-slate-400">
            {toast.message}
          </p>
          <Link
            href={`/tasks/${toast.taskId}`}
            onClick={() => setToast(null)}
            className="mt-2 inline-block text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Open task →
          </Link>
        </div>
      )}
    </div>
  );
}
