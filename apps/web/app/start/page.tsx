"use client";

/**
 * Start: the user's first stop after signing in.
 * - Start a New Project (4 simple setups)
 * - Your projects (continue working)
 * - History (what was done in a project)
 * A project is identified by the name the user gives it; its folder and
 * GitHub repository are only where its code lives.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createProject,
  getProject,
  listProjects,
  openProject,
  setCurrentProjectId,
  type CreateProjectInput,
  type Project,
  type ProjectSetup,
} from "../../lib/api";
import { authHeaders } from "../../lib/auth";
import {
  DirPickerModal,
  fetchWorkspaceRoot,
  hostPath,
  useEscapeKey,
  type WorkspaceRoot,
} from "../../components/FolderPicker";
import { ProjectTools } from "../../components/ProjectTools";

// ---------------------------------------------------------------------------
// Plain-language labels
// ---------------------------------------------------------------------------

const SETUPS: {
  id: ProjectSetup;
  icon: string;
  title: string;
  text: string;
}[] = [
  {
    id: "local_existing",
    icon: "💻",
    title: "A project already on this computer",
    text: "You have the project's files in a folder. Pick that folder and the team improves it.",
  },
  {
    id: "local_new",
    icon: "✨",
    title: "A brand-new project",
    text: "Start from nothing. We create a fresh folder for it on this computer.",
  },
  {
    id: "github_existing",
    icon: "🐙",
    title: "A project already on GitHub",
    text: "Paste the GitHub link. We download a copy so the team can work on it.",
  },
  {
    id: "github_new",
    icon: "🚀",
    title: "A new project on GitHub",
    text: "We create a new GitHub repository for you (public or private) and set it up here.",
  },
];

const STATUS_TEXT: Record<string, { label: string; cls: string }> = {
  pending: { label: "Waiting", cls: "bg-slate-100 text-slate-700" },
  planning: { label: "Planning", cls: "bg-orange-100 text-orange-700" },
  ready_for_review: { label: "Ready for review", cls: "bg-amber-100 text-amber-800" },
  coding: { label: "Coding", cls: "bg-orange-100 text-orange-700" },
  testing: { label: "Testing", cls: "bg-orange-100 text-orange-700" },
  blocked: { label: "Blocked", cls: "bg-red-100 text-red-700" },
  completed: { label: "Completed", cls: "bg-green-100 text-green-700" },
  failed: { label: "Failed", cls: "bg-red-100 text-red-700" },
};

function statusChip(status: string) {
  const s = STATUS_TEXT[status] ?? { label: status.replace(/_/g, " "), cls: "bg-slate-100 text-slate-700" };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}

function whereLabel(p: Project): string {
  if (p.githubUrl) return p.visibility === "private" ? "GitHub · private" : "GitHub · public";
  if (p.localPath) return "On this computer";
  return "Not set up yet";
}

function relTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

// ---------------------------------------------------------------------------
// New project wizard
// ---------------------------------------------------------------------------

function slugify(name: string): string {
  return (
    name
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[-.]+|[-.]+$/g, "")
      .toLowerCase()
      .slice(0, 100) || ""
  );
}

function FolderField({
  id,
  label,
  help,
  value,
  onChange,
  ws,
}: {
  id: string;
  label: string;
  help: string;
  value: string;
  onChange: (v: string) => void;
  ws: WorkspaceRoot | null;
}) {
  const [picker, setPicker] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <div className="flex gap-2">
        <input
          id={id}
          value={hostPath(value, ws)}
          readOnly
          className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
        />
        <button
          type="button"
          onClick={() => setPicker(true)}
          className="rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-sm font-medium text-orange-700 hover:bg-orange-100 dark:border-slate-600 dark:bg-slate-800 dark:text-orange-300"
        >
          Browse…
        </button>
      </div>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{help}</p>
      {picker && <DirPickerModal onSelect={(p) => onChange(p)} onClose={() => setPicker(false)} />}
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  help,
  type = "text",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  help?: string;
  type?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
      />
      {help && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{help}</p>}
    </div>
  );
}

function NewProjectWizard({ onClose, onCreated }: { onClose: () => void; onCreated: (p: Project) => void }) {
  useEscapeKey(onClose);
  const [setup, setSetup] = useState<ProjectSetup | null>(null);
  const [ws, setWs] = useState<WorkspaceRoot | null>(null);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [parentPath, setParentPath] = useState("");
  const [folderName, setFolderName] = useState("");
  const [folderTouched, setFolderTouched] = useState(false);
  const [githubUrl, setGithubUrl] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [token, setToken] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("private");
  const [repoName, setRepoName] = useState("");
  const [repoTouched, setRepoTouched] = useState(false);
  const [fullHistory, setFullHistory] = useState(false);
  const [tokenSaved, setTokenSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchWorkspaceRoot().then((r) => {
      setWs(r);
      setParentPath(r.root);
      setPath(r.root);
    });
    void fetch("/api/settings", { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { githubTokenSet?: boolean } | null) => setTokenSaved(!!d?.githubTokenSet))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!folderTouched) setFolderName(slugify(name));
    if (!repoTouched) setRepoName(slugify(name));
  }, [name, folderTouched, repoTouched]);

  async function submit() {
    setError("");
    if (!name.trim()) return setError("Give your project a name.");
    if (!setup) return;
    const input: CreateProjectInput = { name: name.trim(), setup };
    if (setup === "local_existing") {
      if (!path || (ws && path === ws.root)) return setError("Choose the folder that holds your project.");
      input.path = path;
    } else if (setup === "local_new") {
      if (!folderName) return setError("Choose a folder name.");
      input.parentPath = parentPath;
      input.folderName = folderName;
    } else if (setup === "github_existing") {
      if (!githubUrl.trim()) return setError("Paste the GitHub link of the project.");
      if (isPrivate && !token.trim() && !tokenSaved)
        return setError("A private repository needs a GitHub token.");
      input.githubUrl = githubUrl.trim();
      input.parentPath = parentPath;
      input.fullHistory = fullHistory;
      if (isPrivate && token.trim()) input.githubToken = token.trim();
    } else {
      if (!repoName) return setError("Choose a repository name.");
      if (!token.trim() && !tokenSaved) return setError("Creating a GitHub repository needs a GitHub token.");
      input.repoName = repoName;
      input.visibility = visibility;
      input.parentPath = parentPath;
      if (token.trim()) input.githubToken = token.trim();
    }
    setBusy(true);
    try {
      const p = await createProject(input);
      onCreated(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the project");
    } finally {
      setBusy(false);
    }
  }

  const chosen = SETUPS.find((s) => s.id === setup);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 backdrop-blur-sm sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-project-title"
        className="w-full max-w-2xl rounded-2xl border border-orange-100 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 dark:border-slate-800">
          <div>
            <h2 id="new-project-title" className="text-lg font-bold text-slate-900 dark:text-white">
              {chosen ? chosen.title : "Start a new project"}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {chosen ? chosen.text : "Where is your project? Pick the option that fits."}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800">
            ✕
          </button>
        </div>

        {!setup ? (
          <div className="grid gap-3 p-6 sm:grid-cols-2">
            {SETUPS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSetup(s.id)}
                className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-soft transition hover:-translate-y-0.5 hover:border-orange-300 hover:shadow-glow dark:border-slate-700 dark:bg-slate-900"
              >
                <span className="text-2xl" aria-hidden="true">{s.icon}</span>
                <p className="mt-2 font-semibold text-slate-900 dark:text-white">{s.title}</p>
                <p className="mt-1 text-sm leading-snug text-slate-600 dark:text-slate-400">{s.text}</p>
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-4 p-6">
            <TextField
              id="np-name"
              label="Project name"
              value={name}
              onChange={setName}
              placeholder="e.g. Customer Support AI"
              help="This is how the project appears everywhere. You can rename it later."
            />

            {setup === "local_existing" && (
              <FolderField
                id="np-path"
                label="Project folder"
                help="Choose the folder that contains your project's files. If it isn't tracked with git yet, we start tracking it (your .env files are never included)."
                value={path}
                onChange={setPath}
                ws={ws}
              />
            )}

            {setup === "local_new" && (
              <>
                <FolderField
                  id="np-parent"
                  label="Create it inside"
                  help="Pick where the new project folder should go. You can create a new folder in the picker too."
                  value={parentPath}
                  onChange={setParentPath}
                  ws={ws}
                />
                <TextField
                  id="np-folder"
                  label="Folder name"
                  value={folderName}
                  onChange={(v) => {
                    setFolderTouched(true);
                    setFolderName(v);
                  }}
                  help="Letters, numbers, dots, dashes and underscores."
                />
              </>
            )}

            {setup === "github_existing" && (
              <>
                <TextField
                  id="np-url"
                  label="GitHub link"
                  value={githubUrl}
                  onChange={setGithubUrl}
                  placeholder="https://github.com/company/project"
                />
                <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800">
                  {[false, true].map((priv) => (
                    <button
                      key={String(priv)}
                      type="button"
                      onClick={() => setIsPrivate(priv)}
                      className={`flex-1 rounded-md py-2 text-sm font-medium ${
                        isPrivate === priv ? "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white" : "text-slate-500"
                      }`}
                    >
                      {priv ? "🔒 Private" : "🌐 Public"}
                    </button>
                  ))}
                </div>
                {isPrivate && (
                  <TextField
                    id="np-token"
                    type="password"
                    label={tokenSaved ? "GitHub token (optional, a saved one exists)" : "GitHub token"}
                    value={token}
                    onChange={setToken}
                    placeholder="ghp_…"
                    help="Needed to read a private repository. Stored encrypted for this project only; never shown again."
                  />
                )}
                <FolderField
                  id="np-dest"
                  label="Download it into"
                  help="A folder named after the repository is created here."
                  value={parentPath}
                  onChange={setParentPath}
                  ws={ws}
                />
                <div className="flex items-start gap-2.5 rounded-lg border border-orange-100 bg-orange-50/50 p-3 dark:border-slate-700 dark:bg-slate-800/50">
                  <input
                    id="np-full"
                    type="checkbox"
                    checked={fullHistory}
                    onChange={(e) => setFullHistory(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-orange-600"
                  />
                  <div className="text-sm">
                    <label htmlFor="np-full" className="cursor-pointer font-medium text-slate-800 dark:text-slate-200">
                      Full history
                    </label>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Off (recommended): faster, downloads only the latest version.
                    </p>
                  </div>
                </div>
              </>
            )}

            {setup === "github_new" && (
              <>
                <TextField
                  id="np-repo"
                  label="Repository name on GitHub"
                  value={repoName}
                  onChange={(v) => {
                    setRepoTouched(true);
                    setRepoName(v);
                  }}
                  help="Can differ from the project name. Letters, numbers, dots, dashes and underscores."
                />
                <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800">
                  {(["private", "public"] as const).map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setVisibility(v)}
                      className={`flex-1 rounded-md py-2 text-sm font-medium ${
                        visibility === v ? "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white" : "text-slate-500"
                      }`}
                    >
                      {v === "private" ? "🔒 Private (only you)" : "🌐 Public (everyone)"}
                    </button>
                  ))}
                </div>
                <TextField
                  id="np-token2"
                  type="password"
                  label={tokenSaved ? "GitHub token (optional, a saved one exists)" : "GitHub token"}
                  value={token}
                  onChange={setToken}
                  placeholder="ghp_…"
                  help="Needs permission to create repositories. You can also save it once in Settings."
                />
                <FolderField
                  id="np-dest2"
                  label="Keep a copy in"
                  help="A folder named after the repository is created here."
                  value={parentPath}
                  onChange={setParentPath}
                  ws={ws}
                />
              </>
            )}

            {error && (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
                {error}
              </p>
            )}

            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-between">
              <button
                type="button"
                onClick={() => {
                  setSetup(null);
                  setError("");
                }}
                className="rounded-lg px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                ← Back to options
              </button>
              <button
                type="button"
                onClick={() => void submit()}
                disabled={busy}
                className="rounded-lg bg-orange-600 px-6 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
              >
                {busy ? "Setting up…" : "Create project"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

function HistoryPanel({ projects, initial }: { projects: Project[]; initial: number | null }) {
  const [pid, setPid] = useState<number | null>(initial ?? projects[0]?.id ?? null);
  useEffect(() => {
    if (pid == null && projects[0]) setPid(projects[0].id);
  }, [projects, pid]);
  const { data, isLoading } = useQuery({
    queryKey: ["project", pid],
    queryFn: () => getProject(pid as number),
    enabled: pid != null,
  });

  if (projects.length === 0) {
    return <p className="text-sm text-slate-500">No projects yet. Start a new project first.</p>;
  }

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="history-project" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
          Project
        </label>
        <select
          id="history-project"
          value={pid ?? ""}
          onChange={(e) => setPid(Number(e.target.value))}
          className="w-full max-w-md rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.history.length === 0 && (
        <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          No work has been done in this project yet.
        </p>
      )}
      {data && data.history.length > 0 && (
        <ol className="relative space-y-3 border-l-2 border-orange-100 pl-5 dark:border-slate-700">
          {data.history.map((h) => (
            <li key={h.id} className="relative">
              <span className="absolute -left-[27px] top-3 h-3 w-3 rounded-full border-2 border-white bg-orange-500 dark:border-slate-900" />
              <Link
                href={`/tasks/${h.id}`}
                className="block rounded-xl border border-slate-200 bg-white p-4 shadow-soft transition hover:border-orange-300 dark:border-slate-700 dark:bg-slate-900"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-slate-900 dark:text-white">{h.title}</p>
                  {statusChip(h.status)}
                </div>
                {h.summary && <p className="mt-1 line-clamp-2 text-sm text-slate-600 dark:text-slate-400">{h.summary}</p>}
                <p className="mt-1 text-xs text-slate-400">
                  {relTime(h.updatedAt ?? h.createdAt)} · {h.executionMode === "max" ? "Max" : "Economy"}
                </p>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function StartPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [wizard, setWizard] = useState(false);
  const [tab, setTab] = useState<"projects" | "history">("projects");
  const [historyFor, setHistoryFor] = useState<number | null>(null);
  const [opening, setOpening] = useState<number | null>(null);
  const [tools, setTools] = useState<Project | null>(null);
  const [error, setError] = useState("");

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    // keep polling while a GitHub copy is still downloading
    refetchInterval: (q) =>
      (q.state.data as Project[] | undefined)?.some((p) => p.status === "cloning") ? 3000 : false,
  });

  const sorted = useMemo(() => projects, [projects]);

  async function continueWith(p: Project) {
    setError("");
    setOpening(p.id);
    try {
      await openProject(p.id);
      setCurrentProjectId(p.id);
      router.push(`/tasks?project=${p.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open the project");
      setOpening(null);
    }
  }

  return (
    <main className="space-y-8">
      {/* hero */}
      <section className="relative overflow-hidden rounded-3xl border border-orange-100 bg-gradient-to-br from-white via-orange-50/60 to-orange-100/60 p-6 shadow-soft sm:p-8 dark:border-slate-800 dark:from-slate-900 dark:via-slate-900 dark:to-orange-950/30">
        <div aria-hidden="true" className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-orange-300/30 blur-3xl" />
        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl dark:text-white">
              What would you like to work on?
            </h1>
            <p className="mt-2 max-w-xl text-slate-600 dark:text-slate-300">
              Start a new project or continue one you already have. Then describe the work in
              Tasks and the AI team takes it from there.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setWizard(true)}
            className="btn-primary shrink-0 rounded-xl bg-orange-600 px-6 py-3.5 text-base font-semibold text-white"
          >
            ＋ Start a New Project
          </button>
        </div>
      </section>

      {/* tabs */}
      <div className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm sm:w-fit dark:border-slate-700 dark:bg-slate-900" role="tablist">
        {(
          [
            ["projects", `Your projects${projects.length ? ` (${projects.length})` : ""}`],
            ["history", "History"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`flex-1 rounded-lg px-5 py-2 text-sm font-semibold transition sm:flex-none ${
              tab === id ? "bg-orange-600 text-white shadow-glow" : "text-slate-600 hover:bg-orange-50 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </p>
      )}

      {tab === "projects" ? (
        <section aria-label="Your projects">
          {isLoading && <p className="text-sm text-slate-500">Loading projects…</p>}
          {!isLoading && sorted.length === 0 && (
            <div className="rounded-2xl border border-dashed border-orange-200 p-10 text-center">
              <p className="text-lg font-semibold text-slate-900 dark:text-white">No projects yet</p>
              <p className="mt-1 text-sm text-slate-500">Click “Start a New Project” to begin.</p>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {sorted.map((p) => {
              const total = Object.values(p.taskCounts).reduce((a, b) => a + b, 0);
              const done = p.taskCounts.completed ?? 0;
              return (
                <article
                  key={p.id}
                  className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-soft transition hover:border-orange-200 hover:shadow-glow dark:border-slate-700 dark:bg-slate-900"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="text-base font-bold text-slate-900 dark:text-white">{p.name}</h2>
                    {p.status === "cloning" && (
                      <span className="shrink-0 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
                        Downloading…
                      </span>
                    )}
                    {p.status === "error" && (
                      <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                        Problem
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{whereLabel(p)}</p>
                  {p.status === "error" && p.error && (
                    <p className="mt-2 line-clamp-2 text-xs text-red-600">{p.error}</p>
                  )}
                  <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                    {total === 0 ? "No tasks yet" : `${total} task${total === 1 ? "" : "s"} · ${done} completed`}
                  </p>
                  {p.lastOpenedAt && (
                    <p className="mt-0.5 text-xs text-slate-400">Opened {relTime(p.lastOpenedAt)}</p>
                  )}
                  <div className="mt-4 flex gap-2 pt-1">
                    <button
                      type="button"
                      disabled={p.status === "cloning" || opening === p.id}
                      onClick={() => void continueWith(p)}
                      className="flex-1 rounded-lg bg-orange-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                    >
                      {opening === p.id ? "Opening…" : "Continue"}
                    </button>
                    {p.localPath && p.status === "ready" && (
                      <button
                        type="button"
                        onClick={() => setTools(p)}
                        title="Changes, versions, branches, sync with GitHub"
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-orange-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        Tools
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        setHistoryFor(p.id);
                        setTab("history");
                      }}
                      className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-orange-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                      History
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ) : (
        <section aria-label="History" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-700 dark:bg-slate-900">
          <HistoryPanel key={historyFor ?? "all"} projects={sorted} initial={historyFor} />
        </section>
      )}

      {tools && tools.localPath && (
        <ProjectTools name={tools.name} path={tools.localPath} onClose={() => setTools(null)} />
      )}

      {wizard && (
        <NewProjectWizard
          onClose={() => setWizard(false)}
          onCreated={(p) => {
            setWizard(false);
            void qc.invalidateQueries({ queryKey: ["projects"] });
            setCurrentProjectId(p.id);
            if (p.status === "ready") router.push(`/tasks?project=${p.id}`);
          }}
        />
      )}
    </main>
  );
}
