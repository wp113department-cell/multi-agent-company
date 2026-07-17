"use client";

/**
 * Repo Console — P3 (local workspace + git operations in the browser).
 *
 * Features:
 * - Browse local workspace folders
 * - Clone a remote repo (github/gitlab/bitbucket only)
 * - Git status, log, diff, add, commit, push, branch, checkout, pull
 */

import { useCallback, useEffect, useState } from "react";

const API = "/api/console";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DirEntry {
  name: string;
  path: string;
  type: "dir" | "file";
  size: number | null;
}

interface GitCommit {
  sha: string;
  author: string;
  date: string;
  message: string;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const json = await res.json() as T;
  if (!res.ok) {
    const msg = (json as { detail?: string })?.detail ?? `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return json;
}

function encodePath(p: string) {
  return encodeURIComponent(p);
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ConsolePage() {
  const [browsePath, setBrowsePath] = useState("/home");
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [browseError, setBrowseError] = useState("");
  const [isGitRepo, setIsGitRepo] = useState(false);

  // Clone
  const [cloneUrl, setCloneUrl] = useState("");
  const [cloneDest, setCloneDest] = useState("/home");
  const [cloneBranch, setCloneBranch] = useState("");
  const [cloneLoading, setCloneLoading] = useState(false);
  const [cloneMsg, setCloneMsg] = useState("");

  // Active repo path (selected from browser)
  const [repoPath, setRepoPath] = useState("");

  // Git panels
  const [gitStatus, setGitStatus] = useState("");
  const [gitLog, setGitLog] = useState<GitCommit[]>([]);
  const [gitDiff, setGitDiff] = useState("");
  const [gitBranches, setGitBranches] = useState<string[]>([]);
  const [gitLoading, setGitLoading] = useState(false);
  const [gitMsg, setGitMsg] = useState("");

  // Commit form
  const [commitMsg, setCommitMsg] = useState("");
  const [addPaths, setAddPaths] = useState(".");
  const [newBranch, setNewBranch] = useState("");
  const [activeTab, setActiveTab] = useState<"status"|"log"|"diff"|"branches">("status");

  // Browse workspace
  const browse = useCallback(async (path: string) => {
    setBrowseError("");
    try {
      const res = await apiFetch<{ entries: DirEntry[]; is_git_repo: boolean }>(
        `${API}/workspace/browse`, "POST", { path }
      );
      setEntries(res.entries);
      setIsGitRepo(res.is_git_repo);
      setBrowsePath(path);
    } catch (e) {
      setBrowseError(String(e));
    }
  }, []);

  useEffect(() => { void browse(browsePath); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Git ops
  const loadGitStatus = useCallback(async (p: string) => {
    setGitLoading(true);
    try {
      const res = await apiFetch<{ output: string }>(`${API}/repos/${encodePath(p)}/status`);
      setGitStatus(res.output || "(clean)");
      setActiveTab("status");
    } catch (e) { setGitMsg(String(e)); }
    finally { setGitLoading(false); }
  }, []);

  const loadGitLog = useCallback(async (p: string) => {
    setGitLoading(true);
    try {
      const res = await apiFetch<{ commits: GitCommit[] }>(`${API}/repos/${encodePath(p)}/log?limit=20`);
      setGitLog(res.commits);
      setActiveTab("log");
    } catch (e) { setGitMsg(String(e)); }
    finally { setGitLoading(false); }
  }, []);

  const loadGitDiff = useCallback(async (p: string) => {
    setGitLoading(true);
    try {
      const res = await apiFetch<{ diff: string }>(`${API}/repos/${encodePath(p)}/diff`);
      setGitDiff(res.diff || "(no diff)");
      setActiveTab("diff");
    } catch (e) { setGitMsg(String(e)); }
    finally { setGitLoading(false); }
  }, []);

  const loadBranches = useCallback(async (p: string) => {
    setGitLoading(true);
    try {
      const res = await apiFetch<{ branches: string[] }>(`${API}/repos/${encodePath(p)}/branches`);
      setGitBranches(res.branches);
      setActiveTab("branches");
    } catch (e) { setGitMsg(String(e)); }
    finally { setGitLoading(false); }
  }, []);

  const handleSelectRepo = useCallback((path: string) => {
    setRepoPath(path);
    setGitMsg("");
    void loadGitStatus(path);
  }, [loadGitStatus]);

  const handleClone = useCallback(async () => {
    setCloneLoading(true); setCloneMsg("");
    try {
      await apiFetch(`${API}/repos/clone`, "POST", { url: cloneUrl, dest_path: cloneDest, branch: cloneBranch });
      setCloneMsg("✅ Cloned successfully.");
      void browse(cloneDest);
    } catch (e) { setCloneMsg(`❌ ${String(e)}`); }
    finally { setCloneLoading(false); }
  }, [cloneUrl, cloneDest, cloneBranch, browse]);

  const handleGitAdd = useCallback(async () => {
    if (!repoPath) return;
    setGitLoading(true); setGitMsg("");
    try {
      const paths = addPaths.split(",").map(s => s.trim()).filter(Boolean);
      await apiFetch(`${API}/repos/${encodePath(repoPath)}/add`, "POST", { paths });
      setGitMsg("✅ Staged.");
      void loadGitStatus(repoPath);
    } catch (e) { setGitMsg(`❌ ${String(e)}`); }
    finally { setGitLoading(false); }
  }, [repoPath, addPaths, loadGitStatus]);

  const handleCommit = useCallback(async () => {
    if (!repoPath || !commitMsg) return;
    setGitLoading(true); setGitMsg("");
    try {
      await apiFetch(`${API}/repos/${encodePath(repoPath)}/commit`, "POST", { message: commitMsg });
      setCommitMsg(""); setGitMsg("✅ Committed.");
      void loadGitStatus(repoPath);
    } catch (e) { setGitMsg(`❌ ${String(e)}`); }
    finally { setGitLoading(false); }
  }, [repoPath, commitMsg, loadGitStatus]);

  const handlePush = useCallback(async () => {
    if (!repoPath) return;
    setGitLoading(true); setGitMsg("");
    try {
      await apiFetch(`${API}/repos/${encodePath(repoPath)}/push`, "POST", { remote: "origin" });
      setGitMsg("✅ Pushed.");
    } catch (e) { setGitMsg(`❌ ${String(e)}`); }
    finally { setGitLoading(false); }
  }, [repoPath]);

  const handleCheckout = useCallback(async (createNew: boolean) => {
    if (!repoPath || !newBranch) return;
    setGitLoading(true); setGitMsg("");
    try {
      await apiFetch(`${API}/repos/${encodePath(repoPath)}/checkout`, "POST", { branch: newBranch, create: createNew });
      setGitMsg(`✅ ${createNew ? "Created and checked out" : "Checked out"} branch ${newBranch}.`);
      setNewBranch(""); void loadBranches(repoPath);
    } catch (e) { setGitMsg(`❌ ${String(e)}`); }
    finally { setGitLoading(false); }
  }, [repoPath, newBranch, loadBranches]);

  const handlePull = useCallback(async () => {
    if (!repoPath) return;
    setGitLoading(true); setGitMsg("");
    try {
      const res = await apiFetch<{ stdout: string }>(`${API}/repos/${encodePath(repoPath)}/pull`, "POST", {});
      setGitMsg(`✅ ${res.stdout || "Pulled."}`);
      void loadGitStatus(repoPath);
    } catch (e) { setGitMsg(`❌ ${String(e)}`); }
    finally { setGitLoading(false); }
  }, [repoPath, loadGitStatus]);

  return (
    <main style={{ display: "flex", gap: 16, padding: 16, minHeight: "100vh", fontFamily: "inherit" }}>
      <style>{`
        .console-panel { border-radius: 8px; border: 1px solid #e5e7eb; padding: 14px; background: #fff; }
        .console-panel h2 { font-size: 14px; font-weight: 700; margin: 0 0 12px; color: #111827; }
        .console-panel h3 { font-size: 12px; font-weight: 700; color: #6b7280;
                           text-transform: uppercase; letter-spacing: .05em; margin: 12px 0 6px; }
        .dir-entry { display: flex; align-items: center; gap: 8px; padding: 5px 0;
                    border-bottom: 1px solid #f3f4f6; cursor: pointer; font-size: 13px; }
        .dir-entry:hover { background: #f9fafb; }
        .dir-icon { font-size: 14px; }
        .dir-name { flex: 1; }
        .dir-action { font-size: 11px; color: #3b82f6; margin-left: auto; }
        .console-input { width: 100%; border-radius: 6px; border: 1px solid #d1d5db;
                        padding: 7px 10px; font-size: 13px; margin-bottom: 6px; }
        .console-btn { padding: 6px 14px; border-radius: 6px; border: none; background: #3b82f6;
                      color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; margin-right: 6px; }
        .console-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .console-btn.danger { background: #ef4444; }
        .console-btn.green { background: #22c55e; }
        .console-btn.orange { background: #f59e0b; }
        .tab-bar { display: flex; gap: 4px; margin-bottom: 10px; }
        .tab { padding: 5px 12px; border-radius: 5px; border: 1px solid #e5e7eb;
               font-size: 12px; cursor: pointer; background: #f9fafb; }
        .tab.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }
        .code-out { background: #1e1e2e; color: #cdd6f4; border-radius: 6px; padding: 10px;
                   font-family: monospace; font-size: 11px; white-space: pre-wrap;
                   max-height: 300px; overflow: auto; }
        .git-msg { font-size: 12px; margin-top: 8px; padding: 6px 10px; border-radius: 5px;
                  background: #f0fdf4; border: 1px solid #86efac; }
        .git-msg.err { background: #fef2f2; border-color: #fca5a5; }
        @media (prefers-color-scheme: dark) {
          .console-panel { background: #111827; border-color: #374151; }
          .console-panel h2 { color: #f9fafb; }
          .dir-entry { border-color: #1f2937; }
          .dir-entry:hover { background: #1f2937; }
          .console-input { background: #1f2937; border-color: #374151; color: #f9fafb; }
          .tab { background: #1f2937; border-color: #374151; color: #d1d5db; }
          .tab.active { background: #3b82f6; color: #fff; }
          .git-msg { background: #022c22; border-color: #15803d; color: #d1fae5; }
          .git-msg.err { background: #450a0a; border-color: #dc2626; color: #fecaca; }
        }
      `}</style>

      {/* Left: File Browser + Clone */}
      <div style={{ width: 280, flexShrink: 0, display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="console-panel">
          <h2>📁 Workspace Browser</h2>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <input
              className="console-input"
              style={{ marginBottom: 0, flex: 1 }}
              value={browsePath}
              onChange={e => setBrowsePath(e.target.value)}
              onKeyDown={e => e.key === "Enter" && void browse(browsePath)}
              placeholder="/home/..."
            />
            <button className="console-btn" onClick={() => browse(browsePath)}>Go</button>
          </div>
          {browseError && <p style={{ color: "#ef4444", fontSize: 12 }}>{browseError}</p>}
          <div style={{ maxHeight: 340, overflow: "auto" }}>
            {entries.map(entry => (
              <div className="dir-entry" key={entry.path}>
                <span className="dir-icon">{entry.type === "dir" ? "📂" : "📄"}</span>
                <span className="dir-name">{entry.name}</span>
                {entry.type === "dir" && (
                  <button className="dir-action" onClick={() => void browse(entry.path)}>open</button>
                )}
                {entry.type === "dir" && (
                  <button className="dir-action" style={{ color: "#22c55e" }}
                    onClick={() => handleSelectRepo(entry.path)}>
                    {isGitRepo ? "git" : "select"}
                  </button>
                )}
              </div>
            ))}
          </div>
          {browsePath !== "/" && (
            <button className="console-btn" style={{ marginTop: 8, width: "100%" }}
              onClick={() => {
                const parent = browsePath.split("/").slice(0, -1).join("/") || "/";
                void browse(parent);
              }}>
              ↑ Parent
            </button>
          )}
        </div>

        <div className="console-panel">
          <h2>⬇ Clone Repo</h2>
          <input className="console-input" placeholder="https://github.com/user/repo.git"
            value={cloneUrl} onChange={e => setCloneUrl(e.target.value)} />
          <input className="console-input" placeholder="Destination folder"
            value={cloneDest} onChange={e => setCloneDest(e.target.value)} />
          <input className="console-input" placeholder="Branch (optional)"
            value={cloneBranch} onChange={e => setCloneBranch(e.target.value)} />
          <button className="console-btn green" onClick={handleClone} disabled={cloneLoading || !cloneUrl}>
            {cloneLoading ? "Cloning…" : "Clone"}
          </button>
          {cloneMsg && <p style={{ fontSize: 12, marginTop: 6 }}>{cloneMsg}</p>}
        </div>
      </div>

      {/* Right: Git Panel */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="console-panel">
          <h2>🔀 Git Console {repoPath ? `— ${repoPath}` : "(select a folder)"}</h2>

          {!repoPath && (
            <p style={{ fontSize: 13, color: "#9ca3af" }}>
              Select a folder from the browser to start working with git.
            </p>
          )}

          {repoPath && (
            <>
              {/* Quick actions */}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                <button className="console-btn" onClick={() => loadGitStatus(repoPath)} disabled={gitLoading}>Status</button>
                <button className="console-btn" onClick={() => loadGitLog(repoPath)} disabled={gitLoading}>Log</button>
                <button className="console-btn" onClick={() => loadGitDiff(repoPath)} disabled={gitLoading}>Diff</button>
                <button className="console-btn" onClick={() => loadBranches(repoPath)} disabled={gitLoading}>Branches</button>
                <button className="console-btn orange" onClick={handlePull} disabled={gitLoading}>Pull</button>
                <button className="console-btn danger" onClick={handlePush} disabled={gitLoading}>Push</button>
              </div>

              {/* Tab content */}
              <div className="tab-bar">
                {(["status","log","diff","branches"] as const).map(t => (
                  <button key={t} className={`tab ${activeTab === t ? "active" : ""}`}
                    onClick={() => setActiveTab(t)}>{t}</button>
                ))}
              </div>

              {activeTab === "status" && <div className="code-out">{gitStatus}</div>}
              {activeTab === "diff" && <div className="code-out">{gitDiff}</div>}
              {activeTab === "log" && (
                <div>
                  {gitLog.map(c => (
                    <div key={c.sha} style={{ padding: "6px 0", borderBottom: "1px solid #e5e7eb", fontSize: 12 }}>
                      <code style={{ color: "#8b5cf6" }}>{c.sha.slice(0, 8)}</code>
                      {" · "}
                      <strong>{c.message}</strong>
                      <br />
                      <span style={{ color: "#6b7280" }}>{c.author} · {c.date}</span>
                    </div>
                  ))}
                </div>
              )}
              {activeTab === "branches" && (
                <ul style={{ fontSize: 13, lineHeight: 1.8, margin: 0, padding: "0 0 0 16px" }}>
                  {gitBranches.map(b => <li key={b}>{b}</li>)}
                </ul>
              )}

              {gitMsg && (
                <div className={`git-msg ${gitMsg.startsWith("❌") ? "err" : ""}`}>{gitMsg}</div>
              )}

              {/* Git actions */}
              <h3>Stage &amp; Commit</h3>
              <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                <input className="console-input" style={{ marginBottom: 0, flex: 1 }}
                  placeholder="Files to stage (comma-separated, '.' for all)"
                  value={addPaths} onChange={e => setAddPaths(e.target.value)} />
                <button className="console-btn" onClick={handleGitAdd} disabled={gitLoading}>Stage</button>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <input className="console-input" style={{ marginBottom: 0, flex: 1 }}
                  placeholder="Commit message"
                  value={commitMsg} onChange={e => setCommitMsg(e.target.value)} />
                <button className="console-btn green" onClick={handleCommit}
                  disabled={gitLoading || !commitMsg}>Commit</button>
              </div>

              <h3>Branch</h3>
              <div style={{ display: "flex", gap: 6 }}>
                <input className="console-input" style={{ marginBottom: 0, flex: 1 }}
                  placeholder="Branch name"
                  value={newBranch} onChange={e => setNewBranch(e.target.value)} />
                <button className="console-btn" onClick={() => handleCheckout(false)}
                  disabled={gitLoading || !newBranch}>Checkout</button>
                <button className="console-btn green" onClick={() => handleCheckout(true)}
                  disabled={gitLoading || !newBranch}>New</button>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
