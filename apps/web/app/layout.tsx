import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { NavBar } from "../components/NavBar";

export const metadata: Metadata = {
  title: "Mission Control — Gridiron Developer Department",
  description: "Task queue and agent activity for the Gridiron AI Developer Department.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <Providers>
          <div className="mx-auto max-w-6xl px-4 py-6">
            <NavBar />
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
