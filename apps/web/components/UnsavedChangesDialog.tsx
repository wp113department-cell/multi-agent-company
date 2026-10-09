"use client";

/**
 * W4 (2026-10-09): a task works from the project folder's last commit, so
 * edits the user hasn't committed are invisible to the AI team. Shown when
 * Start finds such edits: save them first (committed, never .env or keys),
 * start without them, or cancel.
 */

import { useEscapeKey } from "./FolderPicker";

export function UnsavedChangesDialog({
  files,
  count,
  busy,
  onSave,
  onIgnore,
  onCancel,
}: {
  files: string[];
  count: number;
  busy: boolean;
  onSave: () => void;
  onIgnore: () => void;
  onCancel: () => void;
}) {
  useEscapeKey(onCancel);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="unsaved-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
        <h2 id="unsaved-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Your folder has unsaved changes
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
          The AI team works from the last version saved in git, so it won&apos;t see these{" "}
          {count === 1 ? "change" : `${count} changes`}:
        </p>
        <ul className="mt-3 max-h-40 overflow-y-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {files.map((f) => (
            <li key={f}>{f}</li>
          ))}
          {count > files.length && <li>… and {count - files.length} more</li>}
        </ul>
        <p className="mt-3 text-xs text-slate-500">
          Saving makes a git commit in your folder. Secret files (.env, keys) are never included.
        </p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 dark:border-slate-700 dark:text-slate-200"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onIgnore}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 dark:border-slate-700 dark:text-slate-200"
          >
            Start without them
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={busy}
            className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Starting…" : "Save them and start"}
          </button>
        </div>
      </div>
    </div>
  );
}
