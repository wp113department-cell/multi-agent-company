"use client";

import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../lib/auth";

/**
 * Folder picker for the workspace folder the API can see. In Docker that is
 * the user's Documents\\multi-agent-workspace (mounted at /workspace); the
 * picker shows the matching path on their computer.
 */

export function useEscapeKey(onEscape: () => void) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") onEscape();
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onEscape]);
}

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

export type WorkspaceRoot = { root: string; host_label: string };

export async function fetchWorkspaceRoot(): Promise<WorkspaceRoot> {
  try {
    const res = await fetch("/api/console/workspace/root", { headers: authHeaders() });
    if (res.ok) return (await res.json()) as WorkspaceRoot;
  } catch {
    // fall through to the historical default
  }
  return { root: "/home", host_label: "" };
}

/** The same folder as seen on the user's computer (Docker setup), else as-is. */
export function hostPath(path: string, ws: WorkspaceRoot | null): string {
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

export function DirPickerModal({ onSelect, onClose }: { onSelect: (path: string) => void; onClose: () => void }) {
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

