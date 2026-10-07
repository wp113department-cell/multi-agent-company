"use client";

/**
 * Agents: every built-in specialist, grouped by what they do, plus the
 * agents the user creates. A created agent is real: it is stored, can be run
 * on a project (read-only: it reads and analyses the code and reports back)
 * and can be deleted.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCustomAgent,
  deleteCustomAgent,
  fetchCustomAgentTools,
  fetchTeamCatalog,
  getCurrentProjectId,
  listCustomAgentRuns,
  listCustomAgents,
  listProjects,
  runCustomAgent,
  type CatalogCategory,
  type CustomAgentRecord,
} from "../../lib/api";
import { useEscapeKey } from "../../components/FolderPicker";
import { Icon } from "../../components/Icon";

const CATEGORY_ICON: Record<string, string> = {
  "Leadership & planning": "compass",
  Developers: "code",
  "Code quality & review": "search",
  Testing: "flask",
  "Security & compliance": "shield",
  "DevOps & reliability": "rocket",
  "Data & databases": "database",
  Documentation: "book",
  "Self-improvement": "trending-up",
  "Specialized engineering": "target",
};

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEscapeKey(onClose);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 backdrop-blur-sm sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-2xl rounded-2xl border border-orange-100 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 dark:border-slate-800">
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- create

function CreateAgentDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { data: tools = [] } = useQuery({ queryKey: ["team-tools"], queryFn: fetchCustomAgentTools });
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [picked, setPicked] = useState<string[]>(["read_file", "list_files", "search_code"]);
  const [caps, setCaps] = useState("");
  const create = useMutation({
    mutationFn: () =>
      createCustomAgent({
        name: name.trim(),
        purpose: purpose.trim(),
        tools: picked,
        capabilities: caps.split(",").map((c) => c.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["custom-agents"] });
      onClose();
    },
  });

  return (
    <Modal title="Create an agent" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div>
          <label htmlFor="ca-name" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Agent name
          </label>
          <input
            id="ca-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Readme Checker"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        <div>
          <label htmlFor="ca-purpose" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
            What should it do?
          </label>
          <textarea
            id="ca-purpose"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            placeholder="e.g. Check that the README explains how to install, configure and run the project, and list anything missing."
            className="h-28 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700 dark:text-slate-300">Tools it may use</legend>
          <p className="mb-2 text-xs text-slate-500">
            Your agents can read and analyse the project, never change files. Editing stays with the built-in developers.
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {tools.map((t) => (
              <div key={t.name} className="flex items-start gap-2 rounded-lg border border-slate-200 px-2.5 py-2 dark:border-slate-700">
                <input
                  id={`tool-${t.name}`}
                  type="checkbox"
                  checked={picked.includes(t.name)}
                  onChange={(e) =>
                    setPicked((p) => (e.target.checked ? [...p, t.name] : p.filter((x) => x !== t.name)))
                  }
                  className="mt-0.5 h-4 w-4 accent-orange-600"
                />
                <div className="min-w-0 text-xs">
                  <label htmlFor={`tool-${t.name}`} className="cursor-pointer font-mono font-semibold text-slate-800 dark:text-slate-200">
                    {t.name}
                  </label>
                  <span className="block truncate text-slate-500" title={t.description}>
                    {t.description}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="ca-caps" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Capabilities (optional, comma separated)
          </label>
          <input
            id="ca-caps"
            value={caps}
            onChange={(e) => setCaps(e.target.value)}
            placeholder="docs-review, onboarding"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        {create.isError && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {create.error instanceof Error ? create.error.message : "Could not create the agent"}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800">
            Cancel
          </button>
          <button
            type="submit"
            disabled={create.isPending || name.trim().length < 2 || purpose.trim().length < 10 || picked.length === 0}
            className="rounded-lg bg-orange-600 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {create.isPending ? "Creating…" : "Create agent"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- view / run

function AgentDetailDialog({ agent, onClose }: { agent: CustomAgentRecord; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState<number | null>(getCurrentProjectId());
  const [request, setRequest] = useState("");
  const { data: runs = [] } = useQuery({
    queryKey: ["custom-agent-runs", agent.id],
    queryFn: () => listCustomAgentRuns(agent.id),
    refetchInterval: (q) =>
      (q.state.data as { status: string }[] | undefined)?.some((r) => r.status === "running") ? 3000 : false,
  });
  const pid = projectId ?? projects[0]?.id ?? null;
  const run = useMutation({
    mutationFn: () => runCustomAgent(agent.id, pid as number, request.trim()),
    onSuccess: () => {
      setRequest("");
      void qc.invalidateQueries({ queryKey: ["custom-agent-runs", agent.id] });
    },
  });
  const projectName = (id: number | null) => projects.find((p) => p.id === id)?.name ?? "—";

  return (
    <Modal title={agent.name} onClose={onClose}>
      <div className="space-y-5">
        <div>
          <p className="text-sm text-slate-700 dark:text-slate-300">{agent.purpose}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {agent.tools.map((t) => (
              <span key={t} className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {t}
              </span>
            ))}
            {agent.capabilities.map((c) => (
              <span key={c} className="rounded-full bg-orange-50 px-2 py-0.5 text-[11px] font-medium text-orange-700 ring-1 ring-orange-200">
                {c}
              </span>
            ))}
          </div>
        </div>

        <form
          className="space-y-3 rounded-xl border border-orange-100 bg-orange-50/40 p-4 dark:border-slate-700 dark:bg-slate-800/40"
          onSubmit={(e) => {
            e.preventDefault();
            run.mutate();
          }}
        >
          <p className="text-sm font-semibold text-slate-900 dark:text-white">Use this agent</p>
          <div>
            <label htmlFor="run-project" className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
              On project
            </label>
            <select
              id="run-project"
              value={pid ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value))}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="run-request" className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
              What do you want to know?
            </label>
            <textarea
              id="run-request"
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              placeholder="e.g. Is the README complete for a new developer?"
              className="h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>
          {run.isError && (
            <p role="alert" className="text-sm text-red-600">
              {run.error instanceof Error ? run.error.message : "Could not start the agent"}
            </p>
          )}
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-slate-500">Uses your Anthropic API key and counts toward the daily budget.</p>
            <button
              type="submit"
              disabled={run.isPending || pid == null || request.trim().length < 3}
              className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-1.5">{!run.isPending && <Icon name="play" size={13} />}{run.isPending ? "Starting…" : "Run"}</span>
            </button>
          </div>
        </form>

        <div>
          <p className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">Results</p>
          {runs.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
          <ul className="space-y-2">
            {runs.map((r) => (
              <li key={r.id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-slate-900 dark:text-white">{r.request}</p>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      r.status === "completed"
                        ? "bg-green-100 text-green-700"
                        : r.status === "running"
                          ? "bg-orange-100 text-orange-700"
                          : "bg-red-100 text-red-700"
                    }`}
                  >
                    {r.status === "running" ? "Working…" : r.status === "completed" ? "Done" : r.status === "blocked" ? "Stopped" : "Failed"}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-slate-400">{projectName(r.projectId)}</p>
                {r.summary && <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-300">{r.summary}</p>}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- page

export default function AgentsPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<CustomAgentRecord | null>(null);

  const { data: catalog, isLoading, error } = useQuery({ queryKey: ["team-catalog"], queryFn: fetchTeamCatalog });
  const { data: mine = [] } = useQuery({ queryKey: ["custom-agents"], queryFn: listCustomAgents });
  const remove = useMutation({
    mutationFn: (id: number) => deleteCustomAgent(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["custom-agents"] }),
  });

  const q = search.trim().toLowerCase();
  const categories: CatalogCategory[] = useMemo(() => {
    const cats = catalog?.categories ?? [];
    if (!q) return cats;
    return cats
      .map((c) => ({
        ...c,
        agents: c.agents.filter(
          (a) => a.displayName.toLowerCase().includes(q) || a.purpose.toLowerCase().includes(q) || a.name.includes(q),
        ),
      }))
      .filter((c) => c.agents.length > 0);
  }, [catalog, q]);

  return (
    <main className="space-y-8">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl leading-relaxed text-slate-900 dark:text-white">Your AI team</h1>
          <p className="mt-1 text-slate-600 dark:text-slate-300">
            {catalog ? `${catalog.total} built-in specialists` : "Built-in specialists"}
            {mine.length > 0 ? ` + ${mine.length} of your own` : ""}. The team picks the right ones for each task automatically.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="btn-primary rounded-xl bg-orange-600 px-5 py-3 text-sm font-semibold text-white"
        >
          <span className="inline-flex items-center gap-1.5"><Icon name="plus" size={16} /> Create Agent</span>
        </button>
      </section>

      {/* your agents */}
      <section aria-label="Your agents">
        <h2 className="mb-3 text-sm font-bold uppercase tracking-wider text-orange-600">Your agents</h2>
        {mine.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-orange-200 p-6 text-center text-sm text-slate-500">
            You haven&apos;t created an agent yet. Use “Create Agent” for a special job, e.g. checking documentation.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {mine.map((a) => (
              <article key={a.id} className="flex flex-col rounded-2xl border border-orange-100 bg-white p-4 shadow-soft dark:border-slate-700 dark:bg-slate-900">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-100 text-orange-700"><Icon name="user" size={16} /></span>
                  <h3 className="font-semibold text-slate-900 dark:text-white">{a.name}</h3>
                </div>
                <p className="mt-2 line-clamp-3 text-sm text-slate-600 dark:text-slate-400">{a.purpose}</p>
                <p className="mt-2 text-xs text-slate-400">{a.tools.length} tools</p>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => setViewing(a)}
                    className="flex-1 rounded-lg bg-orange-600 px-3 py-2 text-sm font-semibold text-white"
                  >
                    Open & run
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Delete the agent “${a.name}”? Its results are deleted too.`)) remove.mutate(a.id);
                    }}
                    className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* built-in */}
      <section aria-label="Built-in agents" className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-sm font-bold uppercase tracking-wider text-orange-600">Built-in specialists</h2>
          <input
            aria-label="Search agents"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search, e.g. security"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm sm:w-64 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
        {isLoading && <p className="text-sm text-slate-500">Loading the team…</p>}
        {error && <p className="text-sm text-red-600">{error instanceof Error ? error.message : "Could not load agents"}</p>}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((c) => {
            const expanded = open === c.name || !!q;
            return (
              <article
                key={c.name}
                className={`rounded-2xl border bg-white shadow-soft transition dark:bg-slate-900 ${
                  expanded ? "border-orange-300 sm:col-span-2 lg:col-span-3" : "border-slate-200 hover:border-orange-200 dark:border-slate-700"
                }`}
              >
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(open === c.name ? null : c.name)}
                  className="flex w-full items-center gap-3 p-4 text-left"
                >
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-orange-100 text-xl">
                    <Icon name={CATEGORY_ICON[c.name] ?? "bot"} size={20} className="text-orange-700" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-slate-900 dark:text-white">{c.name}</span>
                    <span className="block text-xs text-slate-500">{c.description}</span>
                  </span>
                  <span className="rounded-full bg-orange-600 px-2.5 py-0.5 text-sm font-bold text-white">{c.agents.length}</span>
                </button>
                {expanded && (
                  <ul className="grid gap-2 border-t border-orange-100 p-4 sm:grid-cols-2 lg:grid-cols-3 dark:border-slate-800">
                    {c.agents.map((a) => (
                      <li key={a.name} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                        <div className="flex items-center justify-between gap-2">
                          <p className="font-semibold text-slate-900 dark:text-white">{a.displayName}</p>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                              a.available ? "bg-green-100 text-green-700" : "bg-slate-200 text-slate-600"
                            }`}
                          >
                            {a.available ? "Available" : a.state}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-3 text-xs text-slate-600 dark:text-slate-400">{a.purpose}</p>
                        <details className="mt-2 text-xs">
                          <summary className="cursor-pointer font-medium text-orange-700">
                            {a.tools.length} tools{a.capabilities.length ? ` · ${a.capabilities.length} skill${a.capabilities.length === 1 ? "" : "s"}` : ""}
                          </summary>
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {a.capabilities.map((cap) => (
                              <span key={cap} className="rounded-full bg-orange-50 px-1.5 py-0.5 text-[10px] text-orange-700 ring-1 ring-orange-200">
                                {cap}
                              </span>
                            ))}
                            {a.tools.map((t) => (
                              <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                                {t}
                              </span>
                            ))}
                          </div>
                        </details>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            );
          })}
        </div>
      </section>

      {creating && <CreateAgentDialog onClose={() => setCreating(false)} />}
      {viewing && <AgentDetailDialog agent={viewing} onClose={() => setViewing(null)} />}
    </main>
  );
}
