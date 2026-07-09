"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listRepos, cloneRepo, activateRepo, type RepoRecord } from "../../lib/api";

function StatusDot({ status }: { status: string }) {
  if (status === "ready")
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />;
  if (status === "cloning")
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-yellow-400 animate-pulse" />;
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" />;
}

function StatusLabel({ status }: { status: string }) {
  const map: Record<string, string> = {
    ready: "text-green-700",
    cloning: "text-yellow-700",
    error: "text-red-700",
  };
  return (
    <span className={`text-xs font-semibold capitalize ${map[status] ?? "text-slate-500"}`}>
      {status === "cloning" ? "Cloning…" : status}
    </span>
  );
}

function RepoCard({
  repo,
  onActivate,
  activating,
}: {
  repo: RepoRecord;
  onActivate: (id: number) => void;
  activating: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-4 transition-colors ${
        repo.isActive
          ? "border-blue-400 bg-blue-50 dark:border-blue-600 dark:bg-blue-950"
          : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <StatusDot status={repo.status} />
            <span className="font-semibold text-slate-900 dark:text-slate-100 truncate">
              {repo.name}
            </span>
            {repo.isActive && (
              <span className="rounded-full bg-blue-100 dark:bg-blue-900 px-2 py-0.5 text-xs font-semibold text-blue-700 dark:text-blue-300">
                Active
              </span>
            )}
            <StatusLabel status={repo.status} />
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{repo.githubUrl}</p>
          <p className="text-xs text-slate-400 dark:text-slate-500 truncate font-mono mt-0.5">
            {repo.localPath}
          </p>
          {repo.errorMsg && (
            <p className="mt-1 text-xs text-red-600 dark:text-red-400">{repo.errorMsg}</p>
          )}
        </div>
        {repo.status === "ready" && !repo.isActive && (
          <button
            onClick={() => onActivate(repo.id)}
            disabled={activating}
            className="shrink-0 rounded border border-slate-300 dark:border-slate-600 px-3 py-1 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
          >
            {activating ? "Switching…" : "Use this repo"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function RepoPage() {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    refetchInterval: (query) => {
      const repos = query.state.data?.repos ?? [];
      return repos.some((r) => r.status === "cloning") ? 2000 : 10000;
    },
  });

  const cloneMutation = useMutation({
    mutationFn: cloneRepo,
    onSuccess: () => {
      setUrl("");
      setFormError(null);
      qc.invalidateQueries({ queryKey: ["repos"] });
    },
    onError: (e: Error) => setFormError(e.message),
  });

  const activateMutation = useMutation({
    mutationFn: activateRepo,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["repos"] }),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const trimmed = url.trim();
    if (!trimmed) return;
    if (!trimmed.startsWith("https://")) {
      setFormError("URL must start with https://");
      return;
    }
    cloneMutation.mutate(trimmed);
  }

  const repos = data?.repos ?? [];
  const activeRepoPath = data?.activeRepoPath;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Repository</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Paste a GitHub repo URL. Agents will clone it and use it as the codebase for all tasks.
        </p>
      </div>

      {/* Active repo banner */}
      {activeRepoPath && (
        <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950 px-4 py-3">
          <p className="text-xs font-semibold text-green-700 dark:text-green-400 uppercase tracking-wide mb-0.5">
            Currently active
          </p>
          <p className="text-sm font-mono text-green-900 dark:text-green-200 break-all">
            {activeRepoPath}
          </p>
        </div>
      )}

      {/* Clone form */}
      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="flex gap-2">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/your-org/your-repo"
            className="flex-1 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-4 py-2.5 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={cloneMutation.isPending}
          />
          <button
            type="submit"
            disabled={cloneMutation.isPending || !url.trim()}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap"
          >
            {cloneMutation.isPending ? "Cloning…" : "Clone & Use"}
          </button>
        </div>
        {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
        <p className="text-xs text-slate-400 dark:text-slate-500">
          Supports any public https:// Git URL. Private repos require SSH keys set up on this machine.
        </p>
      </form>

      {/* Repo list */}
      <div className="space-y-3">
        {isLoading && <p className="text-sm text-slate-400">Loading…</p>}
        {!isLoading && repos.length === 0 && (
          <p className="text-sm text-slate-400 dark:text-slate-500">
            No repos yet. Paste a GitHub URL above to get started.
          </p>
        )}
        {repos.map((repo) => (
          <RepoCard
            key={repo.id}
            repo={repo}
            onActivate={(id) => activateMutation.mutate(id)}
            activating={activateMutation.isPending}
          />
        ))}
      </div>
    </div>
  );
}
