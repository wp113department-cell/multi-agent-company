/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: [
    "@gridiron/shared-config",
    "@gridiron/shared-db",
    "@gridiron/shared-types",
    "@gridiron/task-engine",
    "@gridiron/agent-runtime",
    "@gridiron/repo-tools",
    "@gridiron/policy-engine",
    "@gridiron/repo-intelligence",
    "@gridiron/context-builder",
    "@gridiron/planning-pipeline",
  ],
  // Prevent webpack from bundling Node.js-only packages — resolve them as native externals
  serverExternalPackages: ["@anthropic-ai/sdk", "glob", "ts-morph", "typescript", "pg"],
};

export default nextConfig;
