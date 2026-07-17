"use client";

import { useEffect, useState } from "react";
import { logout, isAuthenticated } from "../lib/auth";

function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    // Sync with system preference on mount
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

export function NavBar() {
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, []);

  return (
    <header className="mb-6 flex items-center justify-between">
      <a href="/tasks" className="text-lg font-semibold tracking-tight text-slate-900 dark:text-slate-100">
        Mission Control
      </a>
      <nav className="flex items-center gap-3">
        <a href="/chat" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400">Chat</a>
        <a href="/repo" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Repository</a>
        <a href="/tasks" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Tasks</a>
        <a href="/epics" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Epics</a>
        <a href="/goals" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Goals</a>
        <a href="/metrics" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Metrics</a>
        <a href="/cost" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Cost</a>
        <a href="/console" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Console</a>
        <a href="/settings" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Settings</a>
        <ThemeToggle />
        {authed && (
          <button
            onClick={logout}
            className="rounded-md px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-red-50 hover:text-red-600 dark:text-slate-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
          >
            Sign out
          </button>
        )}
      </nav>
    </header>
  );
}
