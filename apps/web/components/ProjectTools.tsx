"use client";

/**
 * Project tools: the git features that used to live in the Console menu,
 * now on the project itself (Start → a project → Tools). Same backend
 * endpoints (/api/console/repos/{path}/...), plain-language labels.
 */

import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../lib/auth";
import { useEscapeKey } from "./FolderPicker";
import { Icon } from "./Icon";

type Tab = "changes" | "history" | "branches" | "save";

interface GitCommit {
  sha: string;
  author: string;
  date: string;
  message: string;
}

async function git<T>(path: string, op: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api/console/repos/${encodeURIComponent(path)}/${op}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T & {
    ok?: boolean;
    stderr?: string;
    detail?: string;
  };
  if (!res.ok) throw new Error(data.detail ?? `Request failed (${res.status})`);
  if (data.ok === false) throw new Error((data.stderr || "The git command failed").trim());
  return data;
}

export function ProjectTools({
  name,
  path,
  onClose,
}: {
  name: string;
  path: string;
  onClose: () => void;
}) {
  useEscapeKey(onClose);
  const [tab, setTab] = useState<Tab>("changes");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [status, setStatus] = useState("");
  const [diff, setDiff] = useState("");
  const [log, setLog] = useState<GitCommit[]>([]);
  const [branches, setBranches] = useState<string[]>([]);
  const [newBranch, setNewBranch] = useState("");
  const [commitMsg, setCommitMsg] = useState("");

  const run = useCallback(async (fn: () => Promise<void>, success?: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      if (success) setMsg({ ok: true, text: success });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }, []);

  const loadChanges = useCallback(
    () =>
      run(async () => {
        const s = await git<{ output: string }>(path, "status");
        setStatus(s.output.trim());
        const d = await git<{ diff?: string; output?: string }>(path, "diff");
        setDiff((d.diff ?? d.output ?? "").trim());
      }),
    [path, run],
  );
  const loadHistory = useCallback(
    () =>
      run(async () => {
        const l = await git<{ commits: GitCommit[] }>(path, "log?limit=30");
        setLog(l.commits);
      }),
    [path, run],
  );
  const loadBranches = useCallback(
    () =>
      run(async () => {
        const b = await git<{ branches: string[] }>(path, "branches");
        setBranches(b.branches);
      }),
    [path, run],
  );

  useEffect(() => {
    if (tab === "changes" || tab === "save") void loadChanges();
    if (tab === "history") void loadHistory();
    if (tab === "branches") void loadBranches();
  }, [tab, loadChanges, loadHistory, loadBranches]);

  const changedFiles = status ? status.split("\n").filter(Boolean) : [];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 backdrop-blur-sm sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-tools-title"
        className="w-full max-w-3xl rounded-2xl border border-orange-100 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 dark:border-slate-800">
          <div className="min-w-0">
            <h2 id="project-tools-title" className="text-lg font-bold text-slate-900 dark:text-white">
              Project tools · {name}
            </h2>
            <p className="truncate font-mono text-xs text-slate-500">{path}</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800">
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="flex gap-1 overflow-x-auto border-b border-slate-100 px-6 pt-3 dark:border-slate-800" role="tablist">
          {(
            [
              ["changes", "Changes"],
              ["history", "History"],
              ["branches", "Branches"],
              ["save", "Save & sync"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={`whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-semibold ${
                tab === id ? "border-b-2 border-orange-500 text-orange-700 dark:text-orange-300" : "text-slate-500 hover:text-slate-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="max-h-[60vh] space-y-3 overflow-y-auto px-6 py-4">
          {busy && <p className="text-sm text-slate-500">Working…</p>}
          {msg && (
            <p
              role={msg.ok ? "status" : "alert"}
              className={`whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                msg.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
              }`}
            >
              {msg.text}
            </p>
          )}

          {tab === "changes" && !busy && (
            <>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {changedFiles.length === 0
                  ? "No unsaved changes. Everything is saved."
                  : `${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"} changed and not saved yet:`}
              </p>
              {changedFiles.length > 0 && (
                <ul className="rounded-lg border border-slate-200 font-mono text-xs dark:border-slate-700">
                  {changedFiles.map((f) => (
                    <li key={f} className="border-b border-slate-100 px-3 py-1.5 last:border-0 dark:border-slate-800">
                      {f}
                    </li>
                  ))}
                </ul>
              )}
              {diff && (
                <pre className="max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{diff}</pre>
              )}
            </>
          )}

          {tab === "history" && !busy && (
            <ol className="space-y-2">
              {log.length === 0 && <p className="text-sm text-slate-500">No saved versions yet.</p>}
              {log.map((c) => (
                <li key={c.sha} className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
                  <p className="text-sm font-medium text-slate-900 dark:text-white">{c.message}</p>
                  <p className="text-xs text-slate-500">
                    {c.author} · {c.date} · <span className="font-mono">{c.sha.slice(0, 7)}</span>
                  </p>
                </li>
              ))}
            </ol>
          )}

          {tab === "branches" && (
            <div className="space-y-3">
              <ul className="flex flex-wrap gap-2">
                {branches.map((b) => (
                  <li key={b}>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await git(path, "checkout", "POST", { branch: b, create: false });
                          await loadBranches();
                        }, `Switched to ${b}.`)
                      }
                      className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-700 hover:border-orange-300 hover:bg-orange-50 dark:border-slate-700 dark:text-slate-200"
                    >
                      {b}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                <input
                  aria-label="New branch name"
                  value={newBranch}
                  onChange={(e) => setNewBranch(e.target.value)}
                  placeholder="new-branch-name"
                  className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                />
                <button
                  type="button"
                  disabled={busy || !newBranch.trim()}
                  onClick={() =>
                    void run(async () => {
                      await git(path, "checkout", "POST", { branch: newBranch.trim(), create: true });
                      setNewBranch("");
                      await loadBranches();
                    }, "Branch created and selected.")
                  }
                  className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                >
                  Create branch
                </button>
              </div>
              <p className="text-xs text-slate-500">Click a branch to switch to it.</p>
            </div>
          )}

          {tab === "save" && (
            <div className="space-y-4">
              <div>
                <label htmlFor="pt-commit" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Save all changes as a new version
                </label>
                <div className="flex gap-2">
                  <input
                    id="pt-commit"
                    value={commitMsg}
                    onChange={(e) => setCommitMsg(e.target.value)}
                    placeholder="What changed? e.g. Update the README"
                    className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                  />
                  <button
                    type="button"
                    disabled={busy || !commitMsg.trim() || changedFiles.length === 0}
                    onClick={() =>
                      void run(async () => {
                        await git(path, "add", "POST", { paths: ["."] });
                        await git(path, "commit", "POST", {
                          message: commitMsg.trim(),
                          author_name: "Multi Agentic Company",
                          author_email: "bot@multi-agentic.local",
                        });
                        setCommitMsg("");
                        await loadChanges();
                      }, "Saved.")
                    }
                    className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
                {changedFiles.length === 0 && <p className="mt-1 text-xs text-slate-500">Nothing to save right now.</p>}
              </div>
              <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await git(path, "pull", "POST", {});
                      await loadChanges();
                    }, "Got the latest version from GitHub.")
                  }
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-orange-50 dark:border-slate-700 dark:text-slate-200"
                >
                  <span className="inline-flex items-center gap-1.5"><Icon name="arrow-down" size={14} /> Get latest from GitHub</span>
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await git(path, "push", "POST", { remote: "origin" });
                    }, "Sent to GitHub.")
                  }
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-orange-50 dark:border-slate-700 dark:text-slate-200"
                >
                  <span className="inline-flex items-center gap-1.5"><Icon name="arrow-up" size={14} /> Send to GitHub</span>
                </button>
              </div>
              <p className="text-xs text-slate-500">
                Tasks save and send their own work automatically after you approve it. Use these only for
                changes you make yourself.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
