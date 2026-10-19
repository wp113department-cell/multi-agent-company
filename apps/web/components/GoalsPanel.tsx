"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { createGoal, fetchGoals, startEpic, type Goal, type GoalEpic } from "../lib/api";

// G11 (2026-10-19): goal → epics for one project. The AI proposes the epics;
// nothing runs until the user starts one, which then goes through the usual
// epic flow (plan, approval, coding, review) on its own page.

const GOAL_STATUS: Record<string, string> = {
  proposed: "Not started",
  in_progress: "In progress",
  done: "Done",
};

function EpicRow({ epic, onStart }: { epic: GoalEpic; onStart: (id: string) => void }) {
  return (
    <li className="flex items-start justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="text-sm text-slate-800 dark:text-slate-200">{epic.title}</p>
        {epic.description && (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{epic.description}</p>
        )}
      </div>
      {epic.status === "proposed" ? (
        <button
          type="button"
          onClick={() => onStart(epic.epicId)}
          className="shrink-0 rounded-lg border border-orange-300 px-3 py-1 text-xs font-semibold text-orange-700 hover:bg-orange-50 dark:border-orange-700 dark:text-orange-300 dark:hover:bg-slate-800"
        >
          Start
        </button>
      ) : (
        <Link
          href={`/epics/${epic.epicId}`}
          className="shrink-0 text-xs font-semibold text-slate-600 underline dark:text-slate-300"
        >
          Open ({epic.status.replace(/_/g, " ")})
        </Link>
      )}
    </li>
  );
}

function GoalCard({ goal, onStart }: { goal: Goal; onStart: (id: string) => void }) {
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{goal.text}</p>
        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {GOAL_STATUS[goal.status] ?? goal.status}
        </span>
      </div>
      {goal.summary && (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{goal.summary}</p>
      )}
      {goal.epics.length > 0 && (
        <ul className="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
          {goal.epics.map((e) => (
            <EpicRow key={e.epicId} epic={e} onStart={onStart} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function GoalsPanel({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const key = ["goals", projectId];
  const { data: goals = [] } = useQuery({
    queryKey: key,
    queryFn: () => fetchGoals(projectId),
    refetchInterval: 30_000,
  });
  // label-only goals (no epics) are shown in Tasks, not here
  const brokenDown = goals.filter((g) => g.epicIds.length > 0);

  const breakDown = useMutation({
    mutationFn: () => createGoal(text.trim(), projectId),
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: key });
    },
  });
  const start = useMutation({
    mutationFn: startEpic,
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  });
  const error = (breakDown.error ?? start.error) as Error | null;

  return (
    <section aria-labelledby="goals-heading" className="space-y-3">
      <div>
        <h2 id="goals-heading" className="text-base text-slate-900 dark:text-slate-100">
          Goals
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Describe a bigger goal. The AI splits it into epics for this project; you start
          each epic when you are ready.
        </p>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) breakDown.mutate();
        }}
        className="flex flex-col gap-2 sm:flex-row"
      >
        <label htmlFor="goal-text" className="sr-only">
          Goal
        </label>
        <input
          id="goal-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Customers can pay online"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-transparent px-3 py-2 text-sm dark:border-slate-700"
        />
        <button
          type="submit"
          disabled={!text.trim() || breakDown.isPending}
          className="rounded-lg bg-orange-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {breakDown.isPending ? "Breaking into epics…" : "Break into epics"}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error.message}
        </p>
      )}
      {brokenDown.length > 0 && (
        <ul className="space-y-3">
          {brokenDown.map((g) => (
            <GoalCard key={g.goalId} goal={g} onStart={(id) => start.mutate(id)} />
          ))}
        </ul>
      )}
    </section>
  );
}
