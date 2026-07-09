"use client";

import { useState, useEffect } from "react";
import { fetchGoals, createGoal, Goal } from "@/lib/api";

function StatusBadge({ status }: { status: string }) {
  const colours: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    processing: "bg-blue-100 text-blue-800",
    completed: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${colours[status] ?? "bg-slate-100 text-slate-700"}`}>
      {status}
    </span>
  );
}

export default function GoalsPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchGoals()
      .then(setGoals)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const goal = await createGoal(text.trim());
      setGoals((prev) => [goal, ...prev]);
      setText("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create goal");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Goals</h1>
      <p className="mb-6 text-sm text-slate-500">
        Describe a business goal in plain English. The Executive Agent will create the epics needed to achieve it.
      </p>

      <form onSubmit={handleSubmit} className="mb-8 flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Improve checkout conversion by 15%..."
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={creating}
        />
        <button
          type="submit"
          disabled={creating || !text.trim()}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {creating ? "Creating…" : "Submit Goal"}
        </button>
      </form>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : goals.length === 0 ? (
        <p className="text-sm text-slate-400">No goals yet. Submit one above.</p>
      ) : (
        <ul className="space-y-3">
          {goals.map((g) => (
            <li key={g.goalId} className="rounded border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <a
                  href={`/goals/${g.goalId}`}
                  className="flex-1 text-sm font-medium text-blue-700 hover:underline"
                >
                  {g.text}
                </a>
                <StatusBadge status={g.status} />
              </div>
              {g.summary && (
                <p className="mt-2 text-xs text-slate-500">{g.summary}</p>
              )}
              <p className="mt-1 text-xs text-slate-400">
                {g.epicIds.length} epic{g.epicIds.length !== 1 ? "s" : ""} created
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
