"use client";

import { RouteError } from "../../components/RouteError";

// Gap-closure Stage 1.4 (answers.md) — route-group error boundary. Keeps
// the root layout (NavBar, Providers) intact when this section throws,
// instead of taking down the whole app shell via the root error.tsx.
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} section="goals" />;
}
