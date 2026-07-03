"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { fetchEpics, createEpic, type Epic } from "../../lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  pending_cost_approval: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  planning: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  coding: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200",
  ready_for_review: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  approved: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  rejected: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  halted: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-100",
};

function EpicStatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function NewEpicForm({ onCreated }: { onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const mutation = useMutation({
    mutationFn: () => createEpic({ title, description }),
    onSuccess: () => {
      setTitle("");
      setDescription("");
      onCreated();
    },
  });

  return (
    <form
      className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 space-y-3 bg-white dark:bg-gray-800"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <h2 className="font-semibold text-gray-900 dark:text-gray-100">New Epic</h2>
      <input
        className="w-full rounded border border-gray-300 dark:border-gray-600 px-3 py-1.5 text-sm dark:bg-gray-700 dark:text-gray-100"
        placeholder="Epic title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />
      <textarea
        className="w-full rounded border border-gray-300 dark:border-gray-600 px-3 py-1.5 text-sm h-20 dark:bg-gray-700 dark:text-gray-100"
        placeholder="Describe the high-level goal…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        required
      />
      <button
        type="submit"
        disabled={mutation.isPending}
        className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
      >
        {mutation.isPending ? "Creating…" : "Create Epic"}
      </button>
      {mutation.isError && (
        <p className="text-sm text-red-600">
          {(mutation.error as Error).message}
        </p>
      )}
    </form>
  );
}

export default function EpicsPage() {
  const qc = useQueryClient();
  const { data: epics, isLoading } = useQuery({
    queryKey: ["epics"],
    queryFn: fetchEpics,
    refetchInterval: 5000,
  });

  return (
    <main className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Epics</h1>

      <NewEpicForm onCreated={() => qc.invalidateQueries({ queryKey: ["epics"] })} />

      {isLoading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}

      {epics && epics.length === 0 && (
        <p className="text-gray-500 dark:text-gray-400">No epics yet. Create one above.</p>
      )}

      <div className="space-y-3">
        {epics?.map((epic) => (
          <Link
            key={epic.epicId}
            href={`/epics/${epic.epicId}`}
            className="block rounded-lg border border-gray-200 dark:border-gray-700 p-4 hover:border-indigo-400 transition-colors bg-white dark:bg-gray-800"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-gray-900 dark:text-gray-100 truncate">{epic.title}</p>
                {epic.haltReason && (
                  <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">{epic.haltReason}</p>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {epic.costEstimate != null && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    ~${epic.costEstimate.toFixed(4)}
                  </span>
                )}
                <EpicStatusBadge status={epic.status} />
              </div>
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}
