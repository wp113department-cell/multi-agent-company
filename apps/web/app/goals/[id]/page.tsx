"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchGoal, Goal } from "@/lib/api";

export default function GoalDetailPage() {
  const params = useParams<{ id: string }>();
  const [goal, setGoal] = useState<Goal | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params.id) return;
    fetchGoal(params.id)
      .then(setGoal)
      .catch((e: Error) => setError(e.message));
  }, [params.id]);

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>;
  }
  if (!goal) {
    return <p className="text-sm text-slate-400">Loading…</p>;
  }

  return (
    <div>
      <a href="/goals" className="mb-4 inline-block text-xs text-blue-600 hover:underline">
        ← All Goals
      </a>

      <div className="rounded border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-2 text-xl font-bold">{goal.text}</h1>
        <div className="mb-4 flex items-center gap-2">
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            {goal.status}
          </span>
          <span className="text-xs text-slate-400">
            {goal.epicIds.length} epic{goal.epicIds.length !== 1 ? "s" : ""}
          </span>
        </div>

        {goal.summary && (
          <div className="mb-6 rounded bg-blue-50 p-4">
            <p className="text-sm font-medium text-blue-800">Executive Summary</p>
            <p className="mt-1 text-sm text-blue-700">{goal.summary}</p>
          </div>
        )}

        {goal.epicIds.length > 0 && (
          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Created Epics</h2>
            <ul className="space-y-1">
              {goal.epicIds.map((id) => (
                <li key={id}>
                  <a
                    href={`/epics/${id}`}
                    className="text-sm text-blue-600 hover:underline"
                  >
                    {id}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
