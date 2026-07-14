import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Mission Control — Gridiron Developer Department",
  description: "Task queue and agent activity for the Gridiron AI Developer Department.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <Providers>
          <div className="mx-auto max-w-6xl px-4 py-6">
            <header className="mb-6 flex items-center justify-between">
              <a href="/tasks" className="text-lg font-semibold tracking-tight">
                Mission Control
              </a>
              <nav className="flex items-center gap-4">
                <a href="/chat" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400">Chat</a>
                <a href="/repo" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Repository</a>
                <a href="/tasks" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Tasks</a>
                <a href="/epics" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Epics</a>
                <a href="/goals" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Goals</a>
                <a href="/metrics" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Metrics</a>
                <a href="/settings" className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400">Settings</a>
              </nav>
            </header>
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
