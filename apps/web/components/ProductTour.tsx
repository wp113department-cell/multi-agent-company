"use client";

import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { isAuthenticated } from "../lib/auth";
import { BrandMark, BRAND_NAME } from "./BrandMark";

/**
 * First-time guided tour. Shown once per browser after the first sign-in;
 * replayable from the navbar ("Tour" button dispatches `mac:start-tour`).
 * Each step highlights a menu item (desktop) or shows a centred card
 * (mobile, where the menu is collapsed).
 */
export const TOUR_DONE_KEY = "mac_tour_done_v1";
export const START_TOUR_EVENT = "mac:start-tour";

type Step = { target?: string; icon: string; title: string; text: string };

const STEPS: Step[] = [
  {
    icon: "👋",
    title: `Welcome to ${BRAND_NAME}`,
    text: "This is your AI software team. Specialised agents plan, write, test and review code, and you approve the important steps. This short tour shows you around the menu.",
  },
  {
    target: "/start",
    icon: "🏁",
    title: "Start",
    text: "Your starting point. Create a new project (on this computer or on GitHub) or continue an existing one, and see its history.",
  },
  {
    target: "/tasks",
    icon: "✅",
    title: "Tasks",
    text: "Describe what you need in plain English (a feature, a bug fix, a refactor). Agents pick it up, and you can follow every step live.",
  },
  {
    target: "/epics",
    icon: "🧩",
    title: "Epics",
    text: "Bigger pieces of work. The planner splits an epic into smaller tasks and runs them in the right order.",
  },
  {
    target: "/goals",
    icon: "🎯",
    title: "Goals & Roadmap",
    text: "Set business goals. The executive agent turns them into a roadmap of epics, so strategy connects to real work.",
  },
  {
    target: "/console",
    icon: "💬",
    title: "Console",
    text: "Chat directly with the AI team, ask questions about your code, or have it make a quick change, with a live terminal view.",
  },
  {
    target: "/agents",
    icon: "🤖",
    title: "Agents",
    text: "Meet the specialists (planner, developer, tester, reviewer, security, DevOps, docs) and see how each one is performing.",
  },
  {
    target: "/fleet",
    icon: "📈",
    title: "Fleet",
    text: "The self-improving part of the company: agents that review the others and propose improvements for you to accept or decline.",
  },
  {
    target: "/approvals",
    icon: "🛡️",
    title: "Approvals",
    text: "Anything risky waits here for you: merges, deployments, sensitive commands. Nothing important happens without your OK.",
  },
  {
    target: "/metrics",
    icon: "📊",
    title: "KPIs",
    text: "Quality, speed and cost at a glance: success rates, test results and the AI spend against your daily budget.",
  },
  {
    target: "/settings",
    icon: "⚙️",
    title: "Settings",
    text: "Team members, roles, integrations and cost limits. You can replay this tour anytime with the Tour button in the top bar.",
  },
  {
    icon: "🚀",
    title: "You're ready!",
    text: "Tip: open Tasks and describe your first job. The team will take it from there and ask you when they need a decision.",
  },
];

type Box = { top: number; left: number; width: number; height: number };

function findTarget(href?: string): HTMLElement | null {
  if (!href) return null;
  const el = document.querySelector<HTMLElement>(`[data-tour="nav-${href}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? el : null; // hidden (mobile menu) → none
}

export function ProductTour() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(0);
  const [box, setBox] = useState<Box | null>(null);

  const start = useCallback(() => {
    setIdx(0);
    setOpen(true);
  }, []);

  // first visit after sign-in
  useEffect(() => {
    if (pathname.startsWith("/login") || !isAuthenticated()) return;
    let done = false;
    try {
      done = localStorage.getItem(TOUR_DONE_KEY) === "1";
    } catch {
      done = true;
    }
    if (!done) {
      const t = setTimeout(start, 700);
      return () => clearTimeout(t);
    }
  }, [pathname, start]);

  useEffect(() => {
    window.addEventListener(START_TOUR_EVENT, start);
    return () => window.removeEventListener(START_TOUR_EVENT, start);
  }, [start]);

  const step = STEPS[idx];

  const measure = useCallback(() => {
    const el = findTarget(step?.target);
    if (!el) {
      setBox(null);
      return;
    }
    const r = el.getBoundingClientRect();
    setBox({ top: r.top - 6, left: r.left - 6, width: r.width + 12, height: r.height + 12 });
  }, [step]);

  useLayoutEffect(() => {
    if (!open) return;
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, measure]);

  const finish = useCallback(() => {
    setOpen(false);
    try {
      localStorage.setItem(TOUR_DONE_KEY, "1");
    } catch {
      // private mode: the tour simply shows again next time
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") finish();
      if (e.key === "ArrowRight") setIdx((i) => Math.min(i + 1, STEPS.length - 1));
      if (e.key === "ArrowLeft") setIdx((i) => Math.max(i - 1, 0));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, finish]);

  if (!open || !step) return null;

  const last = idx === STEPS.length - 1;
  const cardWidth = 360;
  const cardStyle: React.CSSProperties = box
    ? {
        position: "fixed",
        top: box.top + box.height + 14,
        left: Math.max(16, Math.min(box.left + box.width / 2 - cardWidth / 2, window.innerWidth - cardWidth - 16)),
        width: cardWidth,
      }
    : {
        position: "fixed",
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        width: `min(${cardWidth + 60}px, calc(100vw - 32px))`,
      };

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      {box ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed rounded-xl ring-2 ring-orange-400 transition-all duration-300"
          style={{ ...box, boxShadow: "0 0 0 9999px rgba(15,23,42,0.55), 0 0 24px 4px rgba(249,115,22,0.6)" }}
        />
      ) : (
        <div aria-hidden="true" className="fixed inset-0 bg-slate-900/55 backdrop-blur-[2px]" />
      )}

      <div
        style={cardStyle}
        className="rounded-2xl border border-orange-100 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-start gap-3">
          {idx === 0 || last ? (
            <BrandMark size={40} />
          ) : (
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-orange-100 to-orange-200 text-xl">
              {step.icon}
            </span>
          )}
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-orange-600">
              Step {idx + 1} of {STEPS.length}
            </p>
            <h2 id="tour-title" className="text-lg font-bold text-slate-900 dark:text-white">
              {idx === 0 || last ? `${step.icon} ${step.title}` : step.title}
            </h2>
          </div>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{step.text}</p>

        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-orange-100 dark:bg-slate-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-orange-400 to-orange-600 transition-all duration-300"
            style={{ width: `${((idx + 1) / STEPS.length) * 100}%` }}
          />
        </div>

        <div className="mt-4 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={finish}
            className="rounded-lg px-2 py-1.5 text-sm font-medium text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          >
            Skip tour
          </button>
          <div className="flex gap-2">
            {idx > 0 && (
              <button
                type="button"
                onClick={() => setIdx(idx - 1)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Back
              </button>
            )}
            <button
              type="button"
              onClick={() => (last ? finish() : setIdx(idx + 1))}
              className="btn-primary rounded-lg bg-orange-600 px-4 py-1.5 text-sm font-semibold text-white"
            >
              {last ? "Get started" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
