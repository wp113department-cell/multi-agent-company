"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { login } from "../../lib/auth";

// TEMPORARY (requested 2026-09-18) — lets a developer skip typing
// credentials on every reload while testing locally. Uses the same
// admin/DEFAULT_ADMIN_PASSWORD dev default already published in
// docker-compose.yml and .env.example (config.py's default_admin_password),
// not a new secret. REMOVE this button and DEV_LOGIN_USERNAME/
// DEV_LOGIN_PASSWORD before shipping to real users.
const DEV_LOGIN_USERNAME = "admin";
const DEV_LOGIN_PASSWORD = "gridiron123";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [devLoading, setDevLoading] = useState(false);

  async function doLogin(user: string, pass: string) {
    setError(null);
    const result = await login(user, pass);
    if (result.ok) {
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
          Temporary — skips typing credentials for local testing. Will be removed.
        </p>

        <p className="mt-4 text-center text-xs text-slate-400">
          First time?{" "}
          <a href="/api/auth/setup" className="text-blue-500 hover:underline" target="_blank" rel="noreferrer">
            Set up admin account
          </a>
        </p>
      </div>
    </div>
  );
}
