"use client";

/**
 * Tasks: the main working area. Pick the project, create a task (optional
 * goal/epic, priority, Economy/Max), follow each task through its stages.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NewTaskForm } from "../../components/NewTaskForm";
import {
  fetchTasks,
  getCurrentProjectId,
  getProject,
  listProjects,
  setCurrentProjectId,
  startTask,
  type DevTask,
  type StartTaskResult,
} from "../../lib/api";
import { Icon } from "../../components/Icon";
import { UnsavedChangesDialog } from "../../components/UnsavedChangesDialog";

// The statuses a user sees, in lifecycle order, with plain words.
const STATUSES: { id: string; label: string; cls: string; hint: string }[] = [
  { id: "pending", label: "Pending", cls: "bg-slate-100 text-slate-700 ring-slate-200", hint: "Not started yet" },
  { id: "planning", label: "Planning", cls: "bg-sky-100 text-sky-700 ring-sky-200", hint: "The team is making a plan" },
  { id: "ready_for_review", label: "Ready for Review", cls: "bg-amber-100 text-amber-800 ring-amber-200", hint: "Waiting for you" },
  { id: "coding", label: "Coding", cls: "bg-orange-100 text-orange-700 ring-orange-200", hint: "Writing the code" },
  { id: "testing", label: "Testing", cls: "bg-orange-100 text-orange-700 ring-orange-200", hint: "Checking the work" },
  { id: "blocked", label: "Blocked", cls: "bg-red-100 text-red-700 ring-red-200", hint: "Needs attention" },
  { id: "completed", label: "Completed", cls: "bg-green-100 text-green-700 ring-green-200", hint: "Done" },
  { id: "failed", label: "Failed", cls: "bg-red-100 text-red-700 ring-red-200", hint: "Did not finish" },
];
const STATUS_BY_ID = Object.fromEntries(STATUSES.map((s) => [s.id, s]));
const OTHER = { label: "Other", cls: "bg-slate-100 text-slate-600 ring-slate-200", hint: "" };

function StatusChip({ status }: { status: string }) {
  const s = STATUS_BY_ID[status] ?? { ...OTHER, label: status.replace(/_/g, " ") };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${s.cls}`}>
      {s.label}
    </span>
  );
}

function TaskAction({ task }: { task: DevTask }) {
  const qc = useQueryClient();
  const [unsaved, setUnsaved] = useState<StartTaskResult | null>(null);
  const start = useMutation({
    mutationFn: (choice?: "save" | "ignore") => startTask(task.id, choice),
    onSuccess: (r) => {
      setUnsaved(r.triggered ? null : r.unsavedChanges?.length ? r : null);
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const base = "inline-flex items-center justify-center whitespace-nowrap rounded-lg px-3.5 py-1.5 text-sm font-semibold";

  if (task.status === "pending" || task.status === "rejected" || task.status === "blocked") {
    return (
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            start.mutate(undefined);
          }}
          disabled={start.isPending}
          className={`${base} bg-orange-600 text-white disabled:opacity-50`}
        >
          <span className="inline-flex items-center gap-1.5">{!start.isPending && <Icon name={task.status === "pending" ? "play" : "arrow-right"} size={13} />}{start.isPending ? "Starting…" : task.status === "pending" ? "Start" : "Try again"}</span>
        </button>
        {start.isError && (
          <span className="max-w-[14rem] text-right text-xs text-red-600">
            {start.error instanceof Error ? start.error.message : "Could not start"}
          </span>
        )}
        {unsaved && (
          <UnsavedChangesDialog
            files={unsaved.unsavedChanges ?? []}
            count={unsaved.unsavedCount ?? 0}
            busy={start.isPending}
            onSave={() => start.mutate("save")}
            onIgnore={() => start.mutate("ignore")}
            onCancel={() => setUnsaved(null)}
          />
        )}
      </div>
    );
  }
  if (task.status === "ready_for_review") {
    return (
      <Link href={`/tasks/${task.id}`} className={`${base} bg-amber-500 text-white hover:bg-amber-600`}>
        Review plan
      </Link>
    );
  }
  if (["planning", "coding", "testing"].includes(task.status)) {
    return (
      <Link href={`/stream/${task.id}`} className={`${base} border border-orange-200 text-orange-700 hover:bg-orange-50`}>
        Watch live
      </Link>
    );
  }
  return (
    <Link href={`/tasks/${task.id}`} className={`${base} border border-slate-200 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200`}>
      {task.status === "completed" ? "View result" : "View"}
    </Link>
  );
}

function TasksInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [projectId, setProjectId] = useState<number | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const { data: projects = [], isLoading: loadingProjects } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  // project from the URL (?project=), else the remembered one, else the first
  useEffect(() => {
    if (projects.length === 0) return;
    const fromUrl = Number(params.get("project"));
    const remembered = getCurrentProjectId();
    const ids = new Set(projects.map((p) => p.id));
    const pick = ids.has(fromUrl) ? fromUrl : remembered && ids.has(remembered) ? remembered : (projects[0]?.id ?? null);
    setProjectId((cur) => (cur && ids.has(cur) ? cur : pick));
  }, [projects, params]);

  function chooseProject(id: number) {
    setProjectId(id);
    setCurrentProjectId(id);
    router.replace(`/tasks?project=${id}`);
  }

  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId as number),
    enabled: projectId != null,
  });

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ["tasks", "project", projectId],
    queryFn: () => fetchTasks(undefined, null, projectId, 100),
    enabled: projectId != null,
    refetchInterval: 4000,
  });

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const t of tasks) c[t.status] = (c[t.status] ?? 0) + 1;
    return c;
  }, [tasks]);
  const shown = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);
  const waitingForYou = counts.ready_for_review ?? 0;

  if (!loadingProjects && projects.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-orange-200 p-10 text-center">
        <p className="text-lg font-semibold text-slate-900 dark:text-white">No project yet</p>
        <p className="mt-1 text-sm text-slate-500">Tasks belong to a project. Create one in Start first.</p>
        <Link href="/start" className="mt-4 inline-flex rounded-lg bg-orange-600 px-5 py-2.5 text-sm font-semibold text-white">
          Go to Start
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* project bar */}
      <section className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-soft sm:flex-row sm:items-center sm:justify-between dark:border-slate-700 dark:bg-slate-900">
        <div className="flex min-w-0 items-center gap-3">
          <label htmlFor="tasks-project" className="shrink-0 text-sm font-semibold text-slate-700 dark:text-slate-300">
            Project
          </label>
          <select
            id="tasks-project"
            value={projectId ?? ""}
            onChange={(e) => chooseProject(Number(e.target.value))}
            className="min-w-0 flex-1 rounded-lg border border-orange-200 bg-orange-50/50 px-3 py-2 text-sm font-semibold text-slate-900 sm:w-72 sm:flex-none dark:border-slate-600 dark:bg-slate-800 dark:text-white"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {waitingForYou > 0 && (
            <button
              type="button"
              onClick={() => setFilter("ready_for_review")}
              className="rounded-full bg-amber-100 px-3 py-1 font-semibold text-amber-800 ring-1 ring-amber-200"
            >
              {waitingForYou} waiting for your review
            </button>
          )}
          <Link href="/start" className="font-medium text-orange-700 hover:text-orange-800 dark:text-orange-300">
            All projects →
          </Link>
        </div>
      </section>

      <NewTaskForm project={project ?? null} />

      {/* status tabs */}
      <section aria-label="Tasks" className="space-y-3">
        <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Filter by status">
          {[{ id: "all", label: "All" }, ...STATUSES].map((s) => {
            const n = s.id === "all" ? tasks.length : counts[s.id] ?? 0;
            const active = filter === s.id;
            return (
              <button
                key={s.id}
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(s.id)}
                className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
                  active
                    ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                    : "bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-orange-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700"
                }`}
              >
                {s.label}
                <span className={`rounded-full px-1.5 text-[10px] ${active ? "bg-white/20" : "bg-slate-100 dark:bg-slate-800"}`}>{n}</span>
              </button>
            );
          })}
        </div>

        <div className="space-y-2">
          {isLoading && <p className="p-4 text-sm text-slate-500">Loading tasks…</p>}
          {!isLoading && shown.length === 0 && (
            <p className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
              {tasks.length === 0
                ? "No tasks in this project yet. Describe your first one above."
                : "No tasks with this status."}
            </p>
          )}
          {shown.map((task) => (
            <article
              key={task.id}
              className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-soft transition hover:border-orange-200 sm:flex-row sm:items-center sm:justify-between dark:border-slate-700 dark:bg-slate-900"
            >
              <Link href={`/tasks/${task.id}`} className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusChip status={task.status} />
                  {task.priority === "high" && (
                    <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 ring-1 ring-red-200">
                      High priority
                    </span>
                  )}
                  {task.priority !== "high" && (
                    <span className="rounded-full bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700">
                      Medium priority
                    </span>
                  )}
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
                      task.executionMode === "max"
                        ? "bg-orange-50 text-orange-700 ring-orange-200"
                        : "bg-emerald-50 text-emerald-700 ring-emerald-200"
                    }`}
                  >
                    {task.executionMode === "max" ? "Max" : "Economy"}
                  </span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm font-semibold text-slate-900 dark:text-white">{task.title}</p>
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1"><Icon name="folder" size={13} /> {task.projectName ?? project?.name ?? "—"}</span>
                  {task.goalTitle && <span className="inline-flex items-center gap-1"><Icon name="target" size={13} /> {task.goalTitle}</span>}
                  {task.epicTitle && <span className="inline-flex items-center gap-1"><Icon name="layers" size={13} /> {task.epicTitle}</span>}
                  <span>{STATUS_BY_ID[task.status]?.hint ?? ""}</span>
                </p>
              </Link>
              <div className="flex shrink-0 justify-end">
                <TaskAction task={task} />
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function TaskListPage() {
  return (
    <Suspense fallback={<p className="p-4 text-sm text-slate-500">Loading…</p>}>
      <TasksInner />
    </Suspense>
  );
}
