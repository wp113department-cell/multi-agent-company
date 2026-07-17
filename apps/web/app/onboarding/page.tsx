"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { authHeaders } from "../../lib/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DirEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
}

type RepoType = "public" | "private";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

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

async function clonePublic(url: string, dest: string, branch: string): Promise<void> {
  const res = await fetch("/api/console/repos/clone", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ url, dest_path: dest, branch }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Clone failed");
  }
}

async function clonePrivate(url: string, dest: string, token: string, branch: string): Promise<void> {
  const res = await fetch("/api/console/repos/clone-private", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ url, dest_path: dest, token, branch }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Clone failed");
  }
}

// ---------------------------------------------------------------------------
// Directory picker modal
// ---------------------------------------------------------------------------

function DirPickerModal({
  onSelect,
  onClose,
}: {
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const [currentPath, setCurrentPath] = useState("/home");
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [creating, setCreating] = useState(false);

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

  // Navigate to home on first render
  useState(() => { navigate("/home"); });

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
      <div className="mx-4 w-full max-w-md rounded-xl bg-white shadow-2xl dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Select Folder
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>

        {/* Breadcrumb path */}
        <div className="flex items-center gap-1 bg-slate-50 px-4 py-2 font-mono text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-400">
          <span className="truncate">{currentPath}</span>
        </div>

        {/* Up button */}
        <div className="border-b border-slate-100 px-4 py-1 dark:border-slate-800">
          <button
            onClick={() => navigate(parentOf(currentPath))}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-200"
          >
            ↑ Up
          </button>
        </div>

        {/* Directory list */}
        <div className="max-h-56 overflow-y-auto">
          {loading && <p className="px-4 py-3 text-sm text-slate-400">Loading…</p>}
          {!loading && entries.length === 0 && (
            <p className="px-4 py-3 text-sm text-slate-400">Empty directory</p>
          )}
          {!loading && entries.map((e) => (
            <button
              key={e.path}
              onClick={() => navigate(e.path)}
              className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <span className="text-amber-500">📁</span>
              <span className="text-slate-800 dark:text-slate-200">{e.name}</span>
            </button>
          ))}
        </div>

        {/* Create new folder */}
        <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800">
          <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">
            Create new folder here
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="folder-name"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
              onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
            />
            <button
              onClick={handleCreate}
              disabled={!newFolderName.trim() || creating}
              className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              {creating ? "…" : "Create"}
            </button>
          </div>
          {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
        </div>

        {/* Select current folder */}
        <div className="flex justify-end gap-2 border-t border-slate-100 px-4 py-3 dark:border-slate-800">
          <button onClick={onClose} className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={() => { onSelect(currentPath); onClose(); }}
            className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main onboarding page
// ---------------------------------------------------------------------------

export default function OnboardingPage() {
  const router = useRouter();
  const [repoType, setRepoType] = useState<RepoType>("public");

  // Public
  const [pubUrl, setPubUrl] = useState("");
  const [pubFolder, setPubFolder] = useState("");
  const [pubBranch, setPubBranch] = useState("");
  const [showPicker, setShowPicker] = useState(false);

  // Private
  const [privUrl, setPrivUrl] = useState("");
  const [privFolder, setPrivFolder] = useState("");
  const [privToken, setPrivToken] = useState("");
  const [privBranch, setPrivBranch] = useState("");
  const [showPrivPicker, setShowPrivPicker] = useState(false);

  // Clone status
  const [cloning, setCloning] = useState(false);
  const [cloneError, setCloneError] = useState("");
  const [cloneDone, setCloneDone] = useState(false);

  async function handleClone() {
    setCloneError("");
    setCloning(true);
    try {
      if (repoType === "public") {
        if (!pubUrl.trim() || !pubFolder.trim()) throw new Error("Repository URL and folder are required.");
        await clonePublic(pubUrl.trim(), pubFolder.trim(), pubBranch.trim());
      } else {
        if (!privUrl.trim() || !privFolder.trim() || !privToken.trim()) {
          throw new Error("Repository URL, folder, and GitHub token are required.");
        }
        await clonePrivate(privUrl.trim(), privFolder.trim(), privToken.trim(), privBranch.trim());
      }
      setCloneDone(true);
    } catch (e) {
      setCloneError(e instanceof Error ? e.message : "Clone failed");
    } finally {
      setCloning(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
          Set Up Your Repository
        </h1>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Connect the codebase you want the agents to work on. You can add more repos later from the
          Repo page.
        </p>
      </div>

      {/* Repo type toggle */}
      <div className="mb-6 flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800">
        {(["public", "private"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setRepoType(t); setCloneDone(false); setCloneError(""); }}
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

      {/* Public repo form */}
      {repoType === "public" && (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Repository URL
            </label>
            <input
              type="url"
              value={pubUrl}
              onChange={(e) => setPubUrl(e.target.value)}
              placeholder="https://github.com/user/my-project.git"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Clone into folder
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={pubFolder}
                onChange={(e) => setPubFolder(e.target.value)}
                placeholder="/home/user/projects/my-project"
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
            <p className="mt-1 text-xs text-slate-400">
              Type the full path, or click Browse to navigate and select / create a folder.
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Branch (optional)
            </label>
            <input
              type="text"
              value={pubBranch}
              onChange={(e) => setPubBranch(e.target.value)}
              placeholder="main"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>
        </div>
      )}

      {/* Private repo form */}
      {repoType === "private" && (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900">
          <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
            For private GitHub repos, create a{" "}
            <strong>Personal Access Token</strong> at{" "}
            <span className="font-mono">GitHub → Settings → Developer settings → Personal access tokens</span>.
            Grant it <strong>repo</strong> (read/clone) scope. The token is used only for this clone
            and is never stored.
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              GitHub Personal Access Token
            </label>
            <input
              type="password"
              value={privToken}
              onChange={(e) => setPrivToken(e.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Repository URL
            </label>
            <input
              type="url"
              value={privUrl}
              onChange={(e) => setPrivUrl(e.target.value)}
              placeholder="https://github.com/your-org/private-repo.git"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Clone into folder
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={privFolder}
                onChange={(e) => setPrivFolder(e.target.value)}
                placeholder="/home/user/projects/private-repo"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
              <button
                type="button"
                onClick={() => setShowPrivPicker(true)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
              >
                Browse
              </button>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Branch (optional)
            </label>
            <input
              type="text"
              value={privBranch}
              onChange={(e) => setPrivBranch(e.target.value)}
              placeholder="main"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>
        </div>
      )}

      {/* Clone button + status */}
      <div className="mt-4 space-y-3">
        {cloneError && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
            {cloneError}
          </div>
        )}
        {cloneDone && (
          <div className="rounded-lg bg-green-50 px-4 py-3 text-sm font-medium text-green-700 dark:bg-green-900/20 dark:text-green-400">
            ✓ Repository cloned successfully!
          </div>
        )}

        <button
          onClick={handleClone}
          disabled={cloning}
          className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
        >
          {cloning ? "Cloning… this may take a minute" : "Clone Repository"}
        </button>
      </div>

      {/* Skip / Continue to Tasks */}
      <div className="mt-8 flex items-center justify-between border-t border-slate-100 pt-6 dark:border-slate-800">
        <p className="text-xs text-slate-400">
          Already have repos set up? You can skip this step.
        </p>
        <button
          onClick={() => router.push("/tasks")}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          Continue to Tasks →
        </button>
      </div>

      {/* Dir picker modals */}
      {showPicker && (
        <DirPickerModal
          onSelect={(path) => setPubFolder(path)}
          onClose={() => setShowPicker(false)}
        />
      )}
      {showPrivPicker && (
        <DirPickerModal
          onSelect={(path) => setPrivFolder(path)}
          onClose={() => setShowPrivPicker(false)}
        />
      )}
    </div>
  );
}
