/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: [
    "@gridiron/shared-db",
    "@gridiron/shared-types",
    "@gridiron/task-engine",
  ],
};

export default nextConfig;
