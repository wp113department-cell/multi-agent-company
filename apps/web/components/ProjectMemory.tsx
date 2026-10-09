"use client";

/**
 * C3 (2026-10-09): the project's notes — what the user asked the team to
 * remember. Every chat in the project gets all of them with every message.
 */

import { useCallback, useEffect, useState } from "react";
import {
  addProjectNote,
  deleteProjectNote,
  listProjectNotes,
  type ProjectNote,
} from "../lib/api";
import { Icon } from "./Icon";

export function ProjectMemory({ projectId }: { projectId: number }) {
  const [notes, setNotes] = useState<ProjectNote[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    listProjectNotes(projectId)
      .then(setNotes)
      .catch(() => setNotes([]));
  }, [projectId]);
  useEffect(() => {
    load();
  }, [load]);

  async function add() {
    const t = text.trim();
    if (!t) return;
    setError(null);
    try {
      setNotes(await addProjectNote(projectId, t));
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="border-t border-slate-100 p-3 dark:border-slate-800">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-left text-xs font-semibold uppercase tracking-wide text-slate-500"
      >
        <span className="inline-flex items-center gap-1.5">
          <Icon name="lightbulb" size={13} /> Project memory ({notes.length})
        </span>
        <Icon name={open ? "arrow-up" : "arrow-down"} size={12} />
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <p className="text-[11px] text-slate-400">
            Every chat in this project follows these notes.
          </p>
          <ul className="max-h-40 space-y-1 overflow-y-auto">
            {notes.map((n) => (
              <li
                key={n.id}
                className="group flex items-start gap-1 rounded-lg bg-slate-50 px-2 py-1.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                <span className="flex-1">{n.text}</span>
                <button
                  type="button"
                  aria-label={`Forget: ${n.text}`}
                  onClick={() =>
                    void deleteProjectNote(projectId, n.id)
                      .then(setNotes)
                      .catch(() => undefined)
                  }
                  className="rounded p-0.5 text-slate-400 hover:text-red-600"
                >
                  <Icon name="x" size={12} />
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-1">
            <input
              aria-label="Something to remember"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void add();
              }}
              placeholder="e.g. We use pnpm, not npm"
              className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
            <button
              type="button"
              onClick={() => void add()}
              disabled={!text.trim()}
              className="rounded-lg border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200"
            >
              Remember
            </button>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}
    </div>
  );
}
