/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    // `next dev`'s client bundle uses eval() (webpack's eval-source-map
    // devtool, needed for Fast Refresh) to run every module — verified
    // live: with this header's script-src missing 'unsafe-eval', the
    // browser threw "Evaluating a string as JavaScript violates ...
    // 'unsafe-eval' is not an allowed source of script" on every page load
    // and React never hydrated at all (no client component became
    // interactive — every button, the theme toggle, and login all
    // silently did nothing). Production builds (`next build`/`next start`)
    // don't need eval, so 'unsafe-eval' is added to script-src only when
    // NODE_ENV !== 'production', keeping the production CSP exactly as
    // strict as before.
    const isDev = process.env.NODE_ENV !== "production";
    const scriptSrc = isDev
      ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
      : "script-src 'self' 'unsafe-inline'";
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: `default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; ${scriptSrc}; style-src 'self' 'unsafe-inline'; connect-src 'self'`,
          },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
  // Proxy all /api/* requests to the Python FastAPI backend.
  // Set NEXT_PUBLIC_API_URL in apps/web/.env.local to override (e.g. production).
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
