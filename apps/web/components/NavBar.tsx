"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { logout, isAuthenticated, authHeaders } from "../lib/auth";
import { NotificationBell } from "./NotificationBell";
import { BrandMark, BRAND_NAME } from "./BrandMark";
import { START_TOUR_EVENT } from "./ProductTour";
import { Icon } from "./Icon";

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
        >
          <circle cx="12" cy="12" r="5" />
          <line x1="12" y1="1" x2="12" y2="3" />
          <line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
          <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" />
          <line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
          <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </svg>
      ) : (
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
        >
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}

const NAV_LINKS = [
  { href: "/start", label: "Start" },
  { href: "/tasks", label: "Tasks" },
  { href: "/agents", label: "Agents" },
  { href: "/fleet", label: "Fleet & Approvals" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/settings", label: "Settings" },
];

function useFleetPendingCount(authed: boolean): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    // Real bug found during UI audit (2026-09-18): this fetched
    // /api/fleet/requests unconditionally on mount, including on /login
    // before the user is authenticated — every unauthenticated visitor's
    // console showed a 401 for a request they had no way to succeed.
    if (!authed) return;
    let cancelled = false;

    async function refresh() {
      try {
        const res = await fetch("/api/fleet/requests?status=pending", { headers: authHeaders() });
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
  }, [authed]);

  return count;
}

function useApprovalsPendingCount(authed: boolean): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    // Same real bug as useFleetPendingCount above — gated on `authed`.
    if (!authed) return;
    let cancelled = false;

    async function refresh() {
      try {
        const res = await fetch("/api/approvals/pending", { headers: authHeaders() });
        if (!res.ok) return;
        const data = (await res.json()) as { approvals: unknown[] };
        if (!cancelled) setCount(data.approvals.length);
      } catch {
        // non-fatal — badge just stays at its last known value
      }
    }

    void refresh();
    // Skip polls while the tab is hidden (audit 09); refresh resumes when it's visible.
    const interval = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 5000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authed]);

  return count;
}

export function NavBar() {
  const [authed, setAuthed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
  const fleetPending = useFleetPendingCount(authed);
  const approvalsPending = useApprovalsPendingCount(authed);

  // Re-checked on every navigation: signing in happens on /login and then
  // moves to Start without reloading the page, so a mount-only check left
  // the Tour, bell and Sign out buttons hidden until a manual refresh.
  useEffect(() => {
    setAuthed(isAuthenticated());
  }, [pathname]);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // The login page is a full-screen landing page with its own header.
  if (pathname.startsWith("/login")) return null;

  function isActive(href: string) {
    if (href === "/tasks") return pathname === "/tasks" || pathname === "/";
    return pathname.startsWith(href);
  }

  function badge(href: string) {
    const n = href === "/fleet" ? fleetPending + approvalsPending : 0;
    if (n <= 0) return null;
    return (
      <span className="ml-1.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
        {n}
      </span>
    );
  }

  return (
    <header className="sticky top-0 z-40 border-b border-orange-100/80 bg-white/80 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/80">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/start" className="flex shrink-0 items-center gap-2.5" aria-label={`${BRAND_NAME} home`}>
          <BrandMark size={34} />
          <span className="leading-tight">
            <span className="block text-[15px] font-bold tracking-tight text-slate-900 dark:text-white">
              {BRAND_NAME}
            </span>
            <span className="hidden text-[11px] font-medium text-orange-600 sm:block xl:hidden 2xl:block">
              Your AI software team
            </span>
          </span>
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-0 xl:flex">
          {NAV_LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              data-tour={`nav-${href}`}
              aria-current={isActive(href) ? "page" : undefined}
              className={`whitespace-nowrap rounded-lg px-2 py-2 text-[13px] font-medium transition-all 2xl:px-2.5 2xl:text-sm ${
                isActive(href)
                  ? "bg-gradient-to-b from-orange-50 to-orange-100 text-orange-700 shadow-[inset_0_0_0_1px_rgba(251,146,60,0.35)] dark:from-orange-950 dark:to-orange-900/60 dark:text-orange-300"
                  : "text-slate-600 hover:bg-orange-50 hover:text-orange-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              }`}
            >
              {label}
              {badge(href)}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-1">
          {authed && (
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event(START_TOUR_EVENT))}
              title="Take the guided tour"
              className="mr-1 hidden items-center gap-1 whitespace-nowrap rounded-full border border-orange-200 bg-orange-50 px-3 py-1.5 text-xs font-semibold text-orange-700 transition hover:bg-orange-100 md:inline-flex dark:border-orange-900 dark:bg-orange-950/40 dark:text-orange-300"
            >
              <Icon name="sparkles" size={13} /> Tour
            </button>
          )}
          <NotificationBell authed={authed} />
          <ThemeToggle />
          {authed && (
            <button
              onClick={() => void logout()}
              className="ml-1 hidden whitespace-nowrap rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-600 sm:inline-flex dark:border-slate-700 dark:text-slate-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
            >
              Sign out
            </button>
          )}
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            className="ml-1 inline-flex h-9 w-9 items-center justify-center rounded-lg border border-orange-200 text-orange-700 hover:bg-orange-50 xl:hidden dark:border-slate-700 dark:text-orange-300 dark:hover:bg-slate-800"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {menuOpen ? (
                <>
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="6" y1="18" x2="18" y2="6" />
                </>
              ) : (
                <>
                  <line x1="4" y1="7" x2="20" y2="7" />
                  <line x1="4" y1="12" x2="20" y2="12" />
                  <line x1="4" y1="17" x2="20" y2="17" />
                </>
              )}
            </svg>
          </button>
        </div>
      </div>

      {menuOpen && (
        <nav
          id="mobile-nav"
          aria-label="Main mobile"
          className="border-t border-orange-100 bg-white px-4 py-3 shadow-soft xl:hidden dark:border-slate-800 dark:bg-slate-950"
        >
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-4">
            {NAV_LINKS.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                aria-current={isActive(href) ? "page" : undefined}
                className={`flex items-center rounded-lg px-3 py-2.5 text-sm font-medium ${
                  isActive(href)
                    ? "bg-orange-50 text-orange-700 shadow-[inset_0_0_0_1px_rgba(251,146,60,0.35)] dark:bg-orange-950 dark:text-orange-300"
                    : "text-slate-700 hover:bg-orange-50 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {label}
                {badge(href)}
              </Link>
            ))}
          </div>
          {authed && (
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event(START_TOUR_EVENT))}
              className="mt-3 w-full rounded-lg border border-orange-200 bg-orange-50 px-3 py-2.5 text-sm font-semibold text-orange-700 md:hidden dark:border-orange-900 dark:bg-orange-950/40 dark:text-orange-300"
            >
              <span className="inline-flex items-center justify-center gap-1.5"><Icon name="sparkles" size={14} /> Take the guided tour</span>
            </button>
          )}
          {authed && (
            <button
              onClick={() => void logout()}
              className="mt-3 w-full rounded-lg border border-red-200 px-3 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50 sm:hidden dark:border-red-900 dark:text-red-400"
            >
              Sign out
            </button>
          )}
        </nav>
      )}
    </header>
  );
}
