"use client";

// Gap-closure Stage 1.4 (answers.md) — shared UI every route segment's
// error.tsx renders. Next.js App Router requires error.tsx to be a real
// file per segment (no way to share one file across routes), so this
// component is what keeps that UI consistent and DRY instead of
// duplicating markup across ~15 near-identical error.tsx files.
export function RouteError({
  error,
  reset,
  section,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  section?: string;
}) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 rounded-lg border border-red-200 bg-red-50 p-8 text-center dark:border-red-900 dark:bg-red-950/40">
      <p className="text-sm font-medium text-red-800 dark:text-red-300">
        {section ? `Something went wrong in ${section}.` : "Something went wrong."}
      </p>
      <p className="max-w-md text-xs text-red-700/80 dark:text-red-400/80">
        {error.message || "An unexpected error occurred."}
      </p>
      {error.digest && (
        <p className="text-xs text-red-600/60 dark:text-red-500/60">
          Reference: {error.digest}
        </p>
      )}
      <button
        type="button"
        onClick={reset}
        className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
      >
        Try again
      </button>
    </div>
  );
}
