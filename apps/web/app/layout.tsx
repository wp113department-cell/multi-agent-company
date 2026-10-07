import type { Metadata } from "next";
import { Press_Start_2P, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { NavBar } from "../components/NavBar";
import { ProductTour } from "../components/ProductTour";

// Fonts are downloaded at build time and served by the app itself (no
// runtime request to Google; works offline and with the strict CSP).
// Arcade-style pixel font for the logo and headings, a clean modern
// AI-platform font for all other text.
const arcade = Press_Start_2P({ weight: "400", subsets: ["latin"], variable: "--font-arcade", display: "swap" });
const sans = Space_Grotesk({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

export const metadata: Metadata = {
  title: "Multi Agentic Company — AI software team",
  description:
    "Multi Agentic Company: a team of specialised AI agents that plans, codes, tests and reviews software, with humans approving every important step.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${arcade.variable} ${sans.variable}`}>
      <body className="min-h-screen overflow-x-hidden text-slate-900 dark:text-slate-100">
        <Providers>
          <NavBar />
          <ProductTour />
          <div className="mx-auto w-full max-w-[1760px] px-4 pb-12 pt-8 sm:px-8 lg:px-12">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
