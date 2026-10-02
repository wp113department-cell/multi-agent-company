"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { changePassword, login } from "../../lib/auth";

// TEMPORARY (requested 2026-09-18) — lets a developer skip typing
// credentials on every reload while testing locally. Uses the same
// admin/DEFAULT_ADMIN_PASSWORD dev default already published in
// docker-compose.yml and .env.example (config.py's default_admin_password),
// not a new secret.
// Production audit 2026-09-29: shown only under `next dev` (run.sh). Next.js
// inlines NODE_ENV at build time, so a production build drops the button and
// never ships these credentials in the public login bundle.
const DEV_LOGIN_ENABLED = process.env.NODE_ENV === "development";
const DEV_LOGIN_USERNAME = DEV_LOGIN_ENABLED ? "admin" : "";
const DEV_LOGIN_PASSWORD = DEV_LOGIN_ENABLED ? "gridiron123" : "";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [devLoading, setDevLoading] = useState(false);
  // Production audit 14: accounts flagged must_change_password are blocked by
  // the server until they choose a new password here.
  const [stage, setStage] = useState<"login" | "change">("login");
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("change") === "1") setStage("change");
  }, []);

  async function handleChange(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (newPw.length < 8) {
      setError("New password must be at least 8 characters");
      return;
    }
    if (newPw !== confirmPw) {
      setError("The two new passwords do not match");
      return;
    }
    if (newPw === currentPw) {
      setError("Choose a password different from the current one");
      return;
    }
    setLoading(true);
    const result = await changePassword(currentPw, newPw);
    setLoading(false);
    if (result.ok) {
      router.push("/repo");
    } else {
      setError(result.error ?? "Password change failed");
    }
  }

  async function doLogin(user: string, pass: string) {
    setError(null);
    const result = await login(user, pass);
    if (result.ok && result.mustChangePassword) {
      setCurrentPw(pass);
      setStage("change");
    } else if (result.ok) {
      router.push("/repo");
    } else {
      setError(result.error ?? "Login failed");
    }
    return result.ok;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    await doLogin(username, password);
    setLoading(false);
  }

  async function handleDevLogin() {
    setDevLoading(true);
    await doLogin(DEV_LOGIN_USERNAME, DEV_LOGIN_PASSWORD);
    setDevLoading(false);
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <h1 className="mb-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
          Mission Control
        </h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          Sign in to the Gridiron Developer Department
        </p>

        {stage === "change" ? (
          <form onSubmit={handleChange} className="space-y-4" aria-label="Change password">
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
              Choose a new password before continuing.
            </p>
            <div>
              <label
                htmlFor="cp-current"
                className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                Current password
              </label>
              <input
                id="cp-current"
                type="password"
                autoComplete="current-password"
                required
                value={currentPw}
                onChange={(e) => setCurrentPw(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
            <div>
              <label
                htmlFor="cp-new"
                className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                New password
              </label>
              <input
                id="cp-new"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
            <div>
              <label
                htmlFor="cp-confirm"
                className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                Confirm new password
              </label>
              <input
                id="cp-confirm"
                type="password"
                autoComplete="new-password"
                required
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
            {error && (
              <p
                role="alert"
                className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400"
              >
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {loading ? "Saving…" : "Change password"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="login-username"
                className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                Username
              </label>
              <input
                id="login-username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                placeholder="admin"
              />
            </div>

            <div>
              <label
                htmlFor="login-password"
                className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                Password
              </label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}

        {DEV_LOGIN_ENABLED && (
          <>
            <div className="my-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
              <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                Dev shortcut
              </span>
              <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
            </div>

            <button
              type="button"
              onClick={() => void handleDevLogin()}
              disabled={devLoading}
              className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-amber-400 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 disabled:opacity-50 dark:border-amber-500/60 dark:bg-amber-950/30 dark:text-amber-300 dark:hover:bg-amber-950/50"
            >
              <span aria-hidden="true">🛠️</span>
              {devLoading ? "Logging in…" : "Developer Login"}
            </button>
            <p className="mt-1.5 text-center text-[11px] text-amber-600/80 dark:text-amber-400/70">
              Dev mode only — hidden in production builds.
            </p>
          </>
        )}

        {/* The admin account is seeded automatically on first backend start
            (app/main.py lifespan). The old "Set up admin account" link did a
            GET on the POST-only /api/auth/setup, which also returns 409 once
            that seed exists and 404 in production — it could never work. */}
        <p className="mt-4 text-center text-xs text-slate-400">
          First time? Sign in as <span className="font-mono">admin</span> with the{" "}
          <span className="font-mono">DEFAULT_ADMIN_PASSWORD</span> set on the backend.
        </p>
      </div>
    </div>
  );
}
