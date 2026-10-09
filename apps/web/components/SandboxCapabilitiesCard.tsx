"use client";

/**
 * Sol A31 (2026-10-09): what the code sandbox can do, checked for real (the
 * toolchain image is started once and asked which programs it has), so a
 * missing capability is visible here instead of failing halfway through a
 * task.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSandboxCapabilities } from "../lib/api";
import { Icon } from "./Icon";

export function SandboxCapabilitiesCard() {
  const qc = useQueryClient();
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["sandbox-capabilities"],
    queryFn: () => fetchSandboxCapabilities(),
    staleTime: 60_000,
  });
  const rows: [string, boolean][] = data
    ? [
        ...Object.entries(data.programs).map(
          ([p, ok]) => [data.labels[p] ?? p, ok] as [string, boolean],
        ),
        ["Browser tests (installed browsers)", data.browsers],
      ]
    : [];
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Code sandbox</h2>
          <p className="mt-1 text-xs text-slate-500">
            Code and tests run only in throwaway sandbox containers. This is what they can do on
            this computer.
          </p>
        </div>
        <button
          type="button"
          disabled={isFetching}
          onClick={() =>
            void fetchSandboxCapabilities(true).then((d) =>
              qc.setQueryData(["sandbox-capabilities"], d),
            )
          }
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
        >
          {isFetching ? "Checking…" : "Check again"}
        </button>
      </div>
      {isLoading ? (
        <p className="mt-3 text-sm text-slate-400">Checking the sandbox…</p>
      ) : !data?.sandbox ? (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          {data?.note ?? "The sandbox is not available."} Tasks can still plan and write code, but
          cannot run it or its tests.
        </p>
      ) : (
        <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
          {rows.map(([label, ok]) => (
            <li key={label} className="flex items-center gap-2 text-sm">
              <span className={ok ? "text-green-600" : "text-slate-400"}>
                <Icon name={ok ? "check" : "x"} size={14} />
              </span>
              <span className={ok ? "text-slate-700 dark:text-slate-200" : "text-slate-400"}>
                {label}
                {!ok && " — not available"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
