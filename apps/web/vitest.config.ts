import { defineConfig } from "vitest/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  esbuild: {
    // Next.js itself uses the automatic JSX runtime (no `import React` needed
    // in .tsx files) — tsconfig.json's "jsx": "preserve" defers the actual
    // transform to Next's own bundler, but Vitest uses Vite/esbuild directly,
    // which defaults to the classic runtime unless told otherwise.
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next"],
  },
  resolve: {
    alias: {
      "@": dirname,
    },
  },
});
