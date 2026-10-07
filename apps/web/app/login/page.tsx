"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { changePassword, login } from "../../lib/auth";
import { BrandMark, BRAND_NAME } from "../../components/BrandMark";

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
      router.push("/start");
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
      router.push("/start");
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
    <div className="relative -mt-6 ml-[calc(50%-50vw)] min-h-screen w-screen overflow-hidden">
      {/* decorative background */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
        <div className="absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-gradient-to-br from-orange-300/40 via-orange-400/25 to-transparent blur-3xl" />
        <div className="absolute -bottom-48 -left-32 h-[460px] w-[460px] rounded-full bg-gradient-to-tr from-orange-200/50 via-amber-100/40 to-transparent blur-3xl" />
        <div
          className="absolute inset-0 opacity-[0.35] dark:opacity-[0.12]"
          style={{
            backgroundImage:
              "radial-gradient(circle at 1px 1px, rgba(234,88,12,0.18) 1px, transparent 0)",
            backgroundSize: "26px 26px",
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6">
        {/* top bar */}
        <header className="flex h-20 items-center justify-between">
          <div className="flex items-center gap-3">
            <BrandMark size={40} />
            <div className="leading-tight">
              <p className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">{BRAND_NAME}</p>
              <p className="text-xs font-medium text-orange-600">Your AI software team</p>
            </div>
          </div>
          <a
            href="#sign-in"
            className="rounded-full border border-orange-200 bg-white/70 px-4 py-2 text-sm font-semibold text-orange-700 shadow-soft backdrop-blur transition hover:bg-orange-50 lg:hidden dark:border-slate-700 dark:bg-slate-900/70 dark:text-orange-300"
          >
            Sign in
          </a>
        </header>

        <div className="grid items-start gap-10 pb-16 pt-4 lg:grid-cols-[1.25fr_1fr] lg:gap-14 lg:pt-10">
          {/* ---------------- intro ---------------- */}
          <section aria-labelledby="intro-title">
            <span className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-white/80 px-3 py-1 text-xs font-semibold text-orange-700 shadow-soft dark:border-orange-900 dark:bg-slate-900/80 dark:text-orange-300">
              <span className="h-2 w-2 animate-pulseDot rounded-full bg-orange-500" />
              AI agents · Human approval · Safe by design
            </span>
            <h1
              id="intro-title"
              className="mt-5 text-4xl font-extrabold leading-[1.1] tracking-tight text-slate-900 sm:text-5xl dark:text-white"
            >
              A whole software company,
              <br className="hidden sm:block" />{" "}
              <span className="brand-gradient-text">run by AI agents.</span>
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-600 sm:text-lg dark:text-slate-300">
              {BRAND_NAME} is a team of specialised AI agents (planner, developer, tester,
              reviewer, security and DevOps) that turns a plain-English goal into tested, reviewed
              code changes. You stay in control: every important step waits for your approval.
            </p>

            {/* how it works */}
            <h2 className="mt-10 text-sm font-bold uppercase tracking-wider text-orange-600">How it works</h2>
            <ol className="mt-4 grid gap-3 sm:grid-cols-2">
              {STEPS.map((step, idx) => (
                <li
                  key={step.title}
                  className="group relative rounded-2xl border border-orange-100 bg-white/85 p-4 shadow-soft backdrop-blur transition hover:-translate-y-0.5 hover:shadow-glow dark:border-slate-800 dark:bg-slate-900/80"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-orange-400 to-orange-600 text-sm font-bold text-white shadow-glow">
                      {idx + 1}
                    </span>
                    <div>
                      <p className="font-semibold text-slate-900 dark:text-white">{step.title}</p>
                      <p className="mt-1 text-sm leading-snug text-slate-600 dark:text-slate-400">{step.text}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ol>

            {/* agent team */}
            <h2 className="mt-10 text-sm font-bold uppercase tracking-wider text-orange-600">Meet the team</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              {AGENTS.map((a) => (
                <span
                  key={a.name}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                >
                  <span aria-hidden="true">{a.icon}</span>
                  {a.name}
                </span>
              ))}
            </div>

            {/* trust points */}
            <dl className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {TRUST.map((t) => (
                <div
                  key={t.title}
                  className="rounded-2xl border border-slate-200/80 bg-white/70 p-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/60"
                >
                  <dt className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                    <span aria-hidden="true" className="text-orange-500">
                      {t.icon}
                    </span>
                    {t.title}
                  </dt>
                  <dd className="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-400">{t.text}</dd>
                </div>
              ))}
            </dl>
          </section>

          {/* ---------------- sign in ---------------- */}
          <section id="sign-in" aria-label="Sign in" className="lg:sticky lg:top-8">
            <div className="relative">
              <div
                aria-hidden="true"
                className="absolute -inset-1 rounded-[28px] bg-gradient-to-br from-orange-300 via-orange-500 to-orange-700 opacity-60 blur-lg"
              />
              <div className="relative rounded-3xl border border-orange-100 bg-white p-7 shadow-2xl sm:p-8 dark:border-slate-700 dark:bg-slate-900">
                <div className="mb-6 flex items-center gap-3">
                  <div className="animate-floaty">
                    <BrandMark size={44} />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-slate-900 dark:text-white">
                      {stage === "change" ? "Choose a new password" : "Welcome back"}
                    </h2>
                    <p className="text-sm text-slate-500 dark:text-slate-400">Sign in to {BRAND_NAME}</p>
                  </div>
                </div>

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
          </section>
        </div>

        <footer className="border-t border-orange-100 py-6 text-center text-xs text-slate-500 dark:border-slate-800">
          © {new Date().getFullYear()} {BRAND_NAME} · AI agents that plan, build, test and review software
        </footer>
      </div>
    </div>
  );
}

const STEPS = [
  {
    title: "Describe the goal",
    text: "Write what you need in plain English: a feature, a bug fix or an improvement.",
  },
  {
    title: "Agents plan the work",
    text: "The planner splits it into tasks and picks the right specialist for each one.",
  },
  {
    title: "Build & test safely",
    text: "Developers write code and testers run it in an isolated sandbox. Nothing touches your machine.",
  },
  {
    title: "You review & approve",
    text: "See every diff, cost and test result. Approve it and the change is delivered.",
  },
];

const AGENTS = [
  { icon: "🧭", name: "Planner" },
  { icon: "💻", name: "Developer" },
  { icon: "🧪", name: "Tester" },
  { icon: "🔍", name: "Reviewer" },
  { icon: "🛡️", name: "Security" },
  { icon: "🚀", name: "DevOps" },
  { icon: "📚", name: "Docs" },
  { icon: "📈", name: "Self-improvement" },
];

const TRUST = [
  { icon: "✔", title: "Human in control", text: "Risky steps always wait for your approval." },
  { icon: "🔒", title: "Sandboxed", text: "Code runs in isolated containers with no secrets." },
  { icon: "💰", title: "Cost-capped", text: "A daily budget keeps AI spend predictable." },
];
