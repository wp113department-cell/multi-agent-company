import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { NavBar } from "../components/NavBar";
import { ProductTour } from "../components/ProductTour";

export const metadata: Metadata = {
  title: "Multi Agentic Company — AI software team",
  description:
    "Multi Agentic Company: a team of specialised AI agents that plans, codes, tests and reviews software, with humans approving every important step.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen overflow-x-hidden text-slate-900 dark:text-slate-100">
        <Providers>
          <NavBar />
          <ProductTour />
          <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 sm:px-6">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
