"use client";

import { useState, useCallback, useEffect } from "react";

function useEscapeKey(onEscape: () => void) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") onEscape();
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onEscape]);
}
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listRepos, cloneRepo, activateRepo, deleteRepo, type RepoRecord } from "../../lib/api";
import { authHeaders } from "../../lib/auth";

// ---------------------------------------------------------------------------
// Directory picker modal (for Browse button)
// ---------------------------------------------------------------------------

interface DirEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
}

async function browseDir(path: string): Promise<{ entries: DirEntry[]; is_git_repo: boolean }> {
  const res = await fetch("/api/console/workspace/browse", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Browse failed");
  }
  return res.json();
}

type WorkspaceRoot = { root: string; host_label: string };

async function fetchWorkspaceRoot(): Promise<WorkspaceRoot> {
  try {
    const res = await fetch("/api/console/workspace/root", { headers: authHeaders() });
    if (res.ok) return (await res.json()) as WorkspaceRoot;
  } catch {
    // fall through to the historical default
  }
  return { root: "/home", host_label: "" };
}

/** The same folder as seen on the user's computer (Docker setup), else as-is. */
function hostPath(path: string, ws: WorkspaceRoot | null): string {
  if (!ws?.host_label || !path.startsWith(ws.root)) return path;
  const rel = path.slice(ws.root.length).replace(/^\/+/, "");
  if (!rel) return ws.host_label;
  const sep = ws.host_label.includes("\\") ? "\\" : "/";
  return ws.host_label.replace(/[\\/]+$/, "") + sep + rel.split("/").join(sep);
}

async function makeDir(path: string): Promise<void> {
  const res = await fetch("/api/console/workspace/mkdir", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Could not create folder");
  }
}

function DirPickerModal({ onSelect, onClose }: { onSelect: (path: string) => void; onClose: () => void }) {
  const [currentPath, setCurrentPath] = useState("");
  const [ws, setWs] = useState<WorkspaceRoot | null>(null);
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [creating, setCreating] = useState(false);

  useEscapeKey(onClose);

  const navigate = useCallback(async (path: string) => {
    setLoading(true);
    setError("");
    try {
      const data = await browseDir(path);
      setCurrentPath(path);
      setEntries(data.entries.filter((e) => e.type === "dir").sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Browse error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchWorkspaceRoot().then((r) => {
      setWs(r);
      void navigate(r.root);
    });
  }, [navigate]);

  const atRoot = !!ws && currentPath.replace(/\/+$/, "") === ws.root.replace(/\/+$/, "");

  function parentOf(path: string) {
    const parts = path.split("/").filter(Boolean);
    if (parts.length <= 1) return "/";
    return "/" + parts.slice(0, -1).join("/");
  }

  async function handleCreate() {
    if (!newFolderName.trim()) return;
    const newPath = currentPath.replace(/\/$/, "") + "/" + newFolderName.trim();
    setCreating(true);
    setError("");
    try {
      await makeDir(newPath);
      setNewFolderName("");
      await navigate(currentPath);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dir-picker-modal-title"
        className="mx-4 w-full max-w-md rounded-xl bg-white shadow-2xl dark:bg-slate-900"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <h3 id="dir-picker-modal-title" className="text-sm font-semibold text-slate-900 dark:text-slate-100">Select Folder</h3>
          <button onClick={onClose} aria-label="Close dialog" className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300">✕</button>
        </div>
        <div className="bg-orange-50/70 px-4 py-2 dark:bg-slate-800">
          <p className="truncate font-mono text-xs text-slate-700 dark:text-slate-300" title={hostPath(currentPath, ws)}>
            📂 {hostPath(currentPath, ws) || "…"}
          </p>
          {ws?.host_label && (
            <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
              This is your repositories folder on this computer. Choose it or any folder inside it.
            </p>
          )}
        </div>
        <div className="border-b border-slate-100 px-4 py-1 dark:border-slate-800">
          <button
            onClick={() => navigate(parentOf(currentPath))}
            disabled={atRoot}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:text-slate-200"
          >
            ↑ Up
          </button>
        </div>
        <div className="max-h-56 overflow-y-auto">
          {loading && <p className="px-4 py-3 text-sm text-slate-400">Loading…</p>}
          {!loading && entries.length === 0 && <p className="px-4 py-3 text-sm text-slate-400">Empty directory</p>}
          {!loading && entries.map((e) => (
            <button key={e.path} onClick={() => navigate(e.path)} className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800">
              <span className="text-amber-500">📁</span>
              <span className="text-slate-800 dark:text-slate-200">{e.name}</span>
            </button>
          ))}
        </div>
        <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800">
          <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">Create new folder here</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="folder-name"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
              onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
            />
            <button onClick={handleCreate} disabled={!newFolderName.trim() || creating} className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">
              {creating ? "…" : "Create"}
            </button>
          </div>
          {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-4 py-3 dark:border-slate-800">
          <button onClick={onClose} className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800">Cancel</button>
          <button onClick={() => { onSelect(currentPath); onClose(); }} className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clone form (used both inline for first-time setup and inside the add modal)
// ---------------------------------------------------------------------------

type RepoType = "public" | "private";

function CloneForm({
  onSuccess,
  onCancel,
  showCancel,
}: {
  onSuccess: () => void;
  onCancel?: () => void;
  showCancel: boolean;
}) {
  const [repoType, setRepoType] = useState<RepoType>("public");
  const [url, setUrl] = useState("");
  const [folder, setFolder] = useState("");
  const [branch, setBranch] = useState("");
  const [token, setToken] = useState("");
  const [fullHistory, setFullHistory] = useState(false);
  const [ws, setWs] = useState<WorkspaceRoot | null>(null);
  const [showPicker, setShowPicker] = useState(false);

  useEffect(() => {
    void fetchWorkspaceRoot().then((r) => {
      setWs(r);
      setFolder((f) => f || r.root);
    });
  }, []);
  const [cloning, setCloning] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const qc = useQueryClient();

  async function handleClone() {
    setError("");
    const trimUrl = url.trim();
    const trimFolder = folder.trim();
    if (!trimUrl) { setError("Repository URL is required."); return; }
    if (!trimFolder) { setError("Destination folder is required."); return; }
    if (repoType === "private" && !token.trim()) { setError("GitHub token is required for private repos."); return; }

    setCloning(true);
    try {
      await cloneRepo({
        githubUrl: trimUrl,
        destPath: trimFolder,
        branch: branch.trim() || undefined,
        token: repoType === "private" ? token.trim() : undefined,
        fullHistory,
      });
      await qc.invalidateQueries({ queryKey: ["repos"] });
      setDone(true);
      setTimeout(() => onSuccess(), 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Clone failed");
    } finally {
      setCloning(false);
    }
  }

  return (
    <div className="space-y-5">
      {/* Public / Private toggle */}
      <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800">
        {(["public", "private"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setRepoType(t); setError(""); setDone(false); }}
            className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors ${
              repoType === t
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-slate-100"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400"
            }`}
          >
            {t === "public" ? "🌐 Public Repository" : "🔒 Private Repository"}
          </button>
        ))}
      </div>

      <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        {repoType === "private" && (
          <div>
            <label
              htmlFor="repo-github-token"
              className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
            >
              GitHub Personal Access Token
            </label>
            <input
              id="repo-github-token"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
              GitHub → Settings → Developer settings → Personal access tokens. Grant <strong>repo</strong> (read) scope. Not stored.
            </p>
          </div>
        )}

        <div>
          <label
            htmlFor="repo-url"
            className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            Repository URL
          </label>
          <input
            id="repo-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/user/my-project.git"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>

        <div>
          <label
            htmlFor="repo-clone-folder"
            className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            Clone into folder
          </label>
          <div className="flex gap-2">
            <input
              id="repo-clone-folder"
              type="text"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder="/workspace/my-project"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
            <button
              type="button"
              onClick={() => setShowPicker(true)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
            >
              Browse
            </button>
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Click <strong>Browse</strong> to pick or create a folder. If the folder already has files, the
            repository is cloned into a new sub-folder named after it.
            {ws?.host_label && folder.startsWith(ws.root) && (
              <>
                {" "}On this computer: <span className="font-mono">{hostPath(folder, ws)}</span>
              </>
            )}
          </p>
        </div>

        <div>
          <label
            htmlFor="repo-branch"
            className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            Branch (optional)
          </label>
          <input
            id="repo-branch"
            type="text"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="main"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>

        <div className="flex items-start gap-2.5 rounded-lg border border-orange-100 bg-orange-50/50 p-3 dark:border-slate-700 dark:bg-slate-800/50">
          <input
            id="repo-full-history"
            type="checkbox"
            checked={fullHistory}
            onChange={(e) => setFullHistory(e.target.checked)}
            className="mt-0.5 h-4 w-4 accent-orange-600"
          />
          <div className="text-sm">
            <label htmlFor="repo-full-history" className="cursor-pointer font-medium text-slate-800 dark:text-slate-200">
              Full history
            </label>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Off (recommended): fast clone of the latest version only. Turn on if agents need the
              whole commit history. Large repositories can then take many minutes.
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}
      {done && (
        <div className="rounded-lg bg-green-50 px-4 py-3 text-sm font-medium text-green-700 dark:bg-green-900/20 dark:text-green-400">
          ✓ Repository cloning… it will appear in the list shortly.
        </div>
      )}

      <div className="flex gap-3">
        <button
          onClick={handleClone}
          disabled={cloning || done}
          className="flex-1 rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
        >
          {cloning ? "Starting clone…" : "Clone Repository"}
        </button>
        {showCancel && onCancel && (
          <button
            onClick={onCancel}
            className="rounded-lg border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            Cancel
          </button>
        )}
      </div>

      {showPicker && (
        <DirPickerModal
          onSelect={(path) => setFolder(path)}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add repo modal
// ---------------------------------------------------------------------------

function AddRepoModal({ onClose }: { onClose: () => void }) {
  useEscapeKey(onClose);

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/50 px-4 py-12">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-repo-modal-title"
        className="w-full max-w-xl rounded-2xl bg-slate-50 p-6 shadow-2xl dark:bg-slate-950"
      >
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 id="add-repo-modal-title" className="text-lg font-bold text-slate-900 dark:text-slate-100">Add Repository</h2>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              Connect the codebase you want the agents to work on.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            ✕
          </button>
        </div>
        <CloneForm onSuccess={onClose} onCancel={onClose} showCancel={true} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Repo card in the list
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: string }) {
  if (status === "ready") return <span className="inline-block h-2 w-2 rounded-full bg-green-500" />;
  if (status === "cloning") return <span className="inline-block h-2 w-2 rounded-full bg-yellow-400 animate-pulse" />;
  return <span className="inline-block h-2 w-2 rounded-full bg-red-500" />;
}

function RepoCard({
  repo,
  onActivate,
  onRemove,
  activating,
  removing,
}: {
  repo: RepoRecord;
  onActivate: (id: number) => void;
  onRemove: (id: number) => void;
  activating: boolean;
  removing: boolean;
}) {
  const [confirmRemove, setConfirmRemove] = useState(false);

  return (
    <div className={`rounded-xl border p-4 transition-colors ${
      repo.isActive
        ? "border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-950"
        : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
    }`}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-0.5">
            <StatusDot status={repo.status} />
            <span className="font-semibold text-slate-900 dark:text-slate-100 truncate">{repo.name}</span>
            {repo.isActive && (
              <span className="rounded-full bg-blue-100 dark:bg-blue-900 px-2 py-0.5 text-xs font-semibold text-blue-700 dark:text-blue-300">
                Active
              </span>
            )}
            <span className={`text-xs font-semibold capitalize ${
              repo.status === "ready" ? "text-green-700 dark:text-green-400"
              : repo.status === "cloning" ? "text-yellow-600 dark:text-yellow-400"
              : "text-red-600 dark:text-red-400"
            }`}>
              {repo.status === "cloning" ? "Cloning…" : repo.status}
            </span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{repo.githubUrl}</p>
          <p className="text-xs font-mono text-slate-400 dark:text-slate-500 truncate mt-0.5">{repo.localPath}</p>
          {repo.errorMsg && (
            <p className="mt-1 text-xs text-red-600 dark:text-red-400">{repo.errorMsg}</p>
          )}
        </div>

        <div className="shrink-0 flex flex-col gap-2 items-end">
          {repo.status === "ready" && !repo.isActive && (
            <button
              onClick={() => onActivate(repo.id)}
              disabled={activating}
              className="rounded border border-slate-300 dark:border-slate-600 px-3 py-1 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50"
            >
              {activating ? "Switching…" : "Set active"}
            </button>
          )}
          {confirmRemove ? (
            <div className="flex gap-1">
              <button
                onClick={() => onRemove(repo.id)}
                disabled={removing}
                className="rounded border border-red-300 bg-red-50 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-700 dark:bg-red-950 dark:text-red-400 disabled:opacity-50"
              >
                {removing ? "Removing…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirmRemove(false)}
                className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmRemove(true)}
              className="rounded px-2 py-1 text-xs text-slate-400 hover:text-red-600 dark:text-slate-500 dark:hover:text-red-400"
            >
              Remove
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function RepoPage() {
  const qc = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    refetchInterval: (query) => {
      const repos = query.state.data?.repos ?? [];
      return repos.some((r) => r.status === "cloning") ? 2000 : 10000;
    },
  });

  const activateMutation = useMutation({
    mutationFn: activateRepo,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["repos"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteRepo,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["repos"] }),
  });

  const repos = data?.repos ?? [];
  const hasRepos = repos.length > 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-sm text-slate-400">Loading…</p>
      </div>
    );
  }

  // First-time setup: no repos yet
  if (!hasRepos) {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Set Up Your Repository</h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            Connect the codebase you want the agents to work on. You can add more repos later.
          </p>
        </div>
        <CloneForm
          onSuccess={() => qc.invalidateQueries({ queryKey: ["repos"] })}
          showCancel={false}
        />
      </div>
    );
  }

  // Returning user: show repo list
  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Repository</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {repos.length} {repos.length === 1 ? "repo" : "repos"} connected
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <span className="text-base leading-none">+</span>
          Add repo
        </button>
      </div>

      {/* Active repo banner */}
      {data?.activeRepoPath && (
        <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950 px-4 py-3">
          <p className="text-xs font-semibold text-green-700 dark:text-green-400 uppercase tracking-wide mb-0.5">
            Currently active
          </p>
          <p className="text-sm font-mono text-green-900 dark:text-green-200 break-all">
            {data.activeRepoPath}
          </p>
        </div>
      )}

      {/* Repo list */}
      <div className="space-y-3">
        {repos.map((repo) => (
          <RepoCard
            key={repo.id}
            repo={repo}
            onActivate={(id) => activateMutation.mutate(id)}
            onRemove={(id) => deleteMutation.mutate(id)}
            activating={activateMutation.isPending}
            removing={deleteMutation.isPending}
          />
        ))}
      </div>

      {showAddModal && <AddRepoModal onClose={() => setShowAddModal(false)} />}
    </div>
  );
}
