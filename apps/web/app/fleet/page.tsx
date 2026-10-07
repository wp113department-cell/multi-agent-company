"use client";

/**
 * Fleet & Approvals: everything that needs the user's attention in one place.
 * - Approvals: decisions agents are waiting for (plans, risky actions)
 * - Notifications: tasks that got stuck or failed
 * - Team improvements: the self-improvement agents' suggestions + team health
 * - Performance: KPIs and cost (still updated live in the backend)
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ApprovalsPanel } from "../../components/ApprovalsPanel";
import { FleetPanel } from "../../components/FleetPanel";
import { NotificationsPanel } from "../../components/NotificationsPanel";
import { PerformancePanel } from "../../components/PerformancePanel";
import { authHeaders } from "../../lib/auth";

const TABS = [
  { id: "approvals", label: "Approvals" },
  { id: "notifications", label: "Notifications" },
  { id: "improvements", label: "Team improvements" },
  { id: "performance", label: "Performance" },
] as const;
type TabId = (typeof TABS)[number]["id"];

async function count(url: string, pick: (d: unknown) => number): Promise<number> {
  try {
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) return 0;
    return pick(await res.json());
  } catch {
    return 0;
  }
}

function FleetAndApprovals() {
  const router = useRouter();
  const params = useSearchParams();
  const initial = (params.get("tab") as TabId) || "approvals";
  const [tab, setTab] = useState<TabId>(TABS.some((t) => t.id === initial) ? initial : "approvals");
  useEffect(() => {
    const t = params.get("tab") as TabId | null;
    if (t && TABS.some((x) => x.id === t)) setTab(t);
  }, [params]);

  const { data: badges } = useQuery({
    queryKey: ["fleet-approvals-badges"],
    queryFn: async () => ({
      approvals: await count("/api/approvals/pending", (d) =>
        ((d as { approvals: { status: string }[] }).approvals ?? []).filter((a) => a.status === "pending").length,
      ),
      notifications: await count("/api/notifications?days=30&limit=100", (d) => ((d as { items: unknown[] }).items ?? []).length),
      improvements: await count("/api/fleet/requests?status=pending", (d) => (Array.isArray(d) ? d.length : 0)),
    }),
    refetchInterval: 10000,
  });

  function choose(t: TabId) {
    setTab(t);
    router.replace(`/fleet?tab=${t}`);
  }

  return (
    <main className="space-y-6">
      <section>
        <h1 className="text-xl leading-relaxed text-slate-900 dark:text-white">Fleet &amp; Approvals</h1>
        <p className="mt-1 text-slate-600 dark:text-slate-300">
          Everything that needs your attention: decisions to make, problems to look at, and the team&apos;s own
          improvement ideas.
        </p>
      </section>

      <div className="flex gap-1 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900" role="tablist">
        {TABS.map((t) => {
          const n = t.id === "performance" ? 0 : (badges?.[t.id] ?? 0);
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => choose(t.id)}
              className={`inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg px-4 py-2 text-sm font-semibold transition ${
                tab === t.id ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900" : "text-slate-600 hover:bg-orange-50 dark:text-slate-300 dark:hover:bg-slate-800"
              }`}
            >
              {t.label}
              {n > 0 && (
                <span className={`rounded-full px-1.5 text-xs ${t.id === "approvals" ? "bg-red-500 text-white" : "bg-orange-100 text-orange-700"}`}>
                  {n}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <section role="tabpanel">
        {tab === "approvals" && <ApprovalsPanel />}
        {tab === "notifications" && <NotificationsPanel />}
        {tab === "improvements" && <FleetPanel />}
        {tab === "performance" && <PerformancePanel />}
      </section>
    </main>
  );
}

export default function FleetAndApprovalsPage() {
  return (
    <Suspense fallback={<p className="p-4 text-sm text-slate-500">Loading…</p>}>
      <FleetAndApprovals />
    </Suspense>
  );
}
