"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createTask, listRepos } from "../lib/api";

export function NewTaskForm() {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"low" | "medium" | "high">("medium");
  const [repoId, setRepoId] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { data: repoData } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    staleTime: 30000,
  });

  const readyRepos = repoData?.repos.filter((r) => r.status === "ready") ?? [];

  const mutation = useMutation({
    mutationFn: () => createTask({ title, description, repoId }),
    onSuccess: () => {
      setTitle("");
      setDescription("");
      setRepoId(null);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  return (
    <form
      className="mb-6 space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) mutation.mutate();
      }}
    >
      <h2 className="text-sm font-semibold text-slate-700">Submit a development task</h2>
      <input
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        placeholder="Title, e.g. Add a new endpoint that shows worker queue status"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />
      <textarea
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        placeholder="Description (optional)"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <div className="flex items-center gap-2 flex-wrap">
        <select
          className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          value={priority}
          onChange={(e) => setPriority(e.target.value as typeof priority)}
        >
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>

        {/* Repo selector */}
        <select
          className="rounded border border-slate-300 px-2 py-1.5 text-sm flex-1 min-w-0"
          value={repoId ?? ""}
          onChange={(e) => setRepoId(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">Default repo</option>
          {readyRepos.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} {r.isActive ? "(active)" : ""}
            </option>
          ))}
        </select>

        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 whitespace-nowrap"
        >
          {mutation.isPending ? "Submitting…" : "Submit task"}
        </button>
      </div>
      {mutation.isError && (
        <p className="text-sm text-red-600">{(mutation.error as Error).message}</p>
      )}
    </form>
  );
}
