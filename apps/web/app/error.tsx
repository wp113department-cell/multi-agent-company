"use client";

// Gap-closure Stage 1.4 (answers.md) — before this, any unhandled render
// error anywhere in the app fell through to Next.js's default unstyled
// crash screen (or a blank page in production), with no boundary at all.
// This is the last-resort, root-level catch: if a segment-level error.tsx
// (app/<route>/error.tsx) doesn't already handle it, this does. Must
// render its own <html>/<body> — a root error.tsx can be triggered by the
// root layout itself throwing, so it cannot assume layout.tsx's shell is
// still standing (Next.js App Router requirement, not a stylistic choice).
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center bg-slate-50 p-6 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <div className="flex max-w-lg flex-col items-center gap-4 rounded-lg border border-red-200 bg-red-50 p-8 text-center dark:border-red-900 dark:bg-red-950/40">
          <p className="text-lg font-semibold text-red-800 dark:text-red-300">
            Something went wrong.
          </p>
          <p className="text-sm text-red-700/80 dark:text-red-400/80">
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
      </body>
    </html>
  );
}
