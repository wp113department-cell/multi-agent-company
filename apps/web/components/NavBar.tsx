"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { logout, isAuthenticated } from "../lib/auth";

function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("gridiron_theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = stored ? stored === "dark" : prefersDark;
    setDark(isDark);
    document.documentElement.classList.toggle("dark", isDark);
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    localStorage.setItem("gridiron_theme", next ? "dark" : "light");
    document.documentElement.classList.toggle("dark", next);
  }

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
    >
      {dark ? (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      )}
    </button>
  );
}

const NAV_LINKS = [
  { href: "/repo", label: "Repository" },
  { href: "/tasks", label: "Tasks" },
  { href: "/epics", label: "Epics" },
  { href: "/goals", label: "Goals" },
  { href: "/console", label: "Console" },
  { href: "/agents", label: "Agents" },
  { href: "/fleet", label: "Fleet" },
  { href: "/approvals", label: "Approvals" },
  { href: "/metrics", label: "KPIs" },
  { href: "/settings", label: "Settings" },
];

function useFleetPendingCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const res = await fetch("/api/fleet/requests?status=pending");
        if (!res.ok) return;
        const data = (await res.json()) as unknown[];
        if (!cancelled) setCount(data.length);
      } catch {
        // non-fatal — badge just stays at its last known value
      }
    }

    void refresh();
    const es = new EventSource("/api/fleet/requests/stream");
    es.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as { type: string };
        if (event.type === "new_request" || event.type === "status_changed") void refresh();
      } catch {
        // ignore ping/parse errors
      }
    };

    return () => {
      cancelled = true;
      es.close();
    };
  }, []);

  return count;
}

function useApprovalsPendingCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const res = await fetch("/api/approvals/pending");
        if (!res.ok) return;
        const data = (await res.json()) as { approvals: unknown[] };
        if (!cancelled) setCount(data.approvals.length);
      } catch {
        // non-fatal — badge just stays at its last known value
      }
    }

    void refresh();
    const interval = setInterval(() => void refresh(), 5000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return count;
}

export function NavBar() {
  const [authed, setAuthed] = useState(false);
  const pathname = usePathname();
  const fleetPending = useFleetPendingCount();
  const approvalsPending = useApprovalsPendingCount();

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, []);

  function isActive(href: string) {
    if (href === "/tasks") return pathname === "/tasks" || pathname === "/";
    return pathname.startsWith(href);
  }

  return (
    <header className="mb-6 flex items-center justify-between">
      <a href="/tasks" className="text-lg font-semibold tracking-tight text-slate-900 dark:text-slate-100">
        Mission Control
      </a>
      <nav className="flex items-center gap-1">
        {NAV_LINKS.map(({ href, label }) => (
          <a
            key={href}
            href={href}
            className={`rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors ${
              isActive(href)
                ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            }`}
          >
            {label}
            {href === "/fleet" && fleetPending > 0 && (
              <span className="ml-1.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
                {fleetPending}
              </span>
            )}
            {href === "/approvals" && approvalsPending > 0 && (
              <span className="ml-1.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
                {approvalsPending}
              </span>
            )}
          </a>
        ))}
        <div className="mx-1 h-4 w-px bg-slate-200 dark:bg-slate-700" />
        <ThemeToggle />
        {authed && (
          <button
            onClick={logout}
            className="ml-1 rounded-md px-2.5 py-1.5 text-sm font-medium text-slate-500 hover:bg-red-50 hover:text-red-600 dark:text-slate-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
          >
            Sign out
          </button>
        )}
      </nav>
    </header>
  );
}
