/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Hide the Next.js dev-tools badge (the round "N" in the corner): it only
  // exists under `next dev`, but local demos run that way too.
  devIndicators: false,
  // Real bug found live (2026-09-25, Q12/#12 UI gap-closure verification):
  // Next.js's own default compression (gzip, enabled by `compress: true`
  // implicitly) applies to EVERY proxied response, including the chat
  // agent's streaming /api/chat/sessions/{id}/messages endpoint — verified
  // directly with curl: through this proxy the response carries
  // `Content-Encoding: gzip`; hit the backend on :8000 directly with the
  // same Accept-Encoding header and there's none. Node's gzip stream
  // buffers internally and does not flush per chunk, so a real browser
  // (which always advertises gzip support) received two terminal_output
  // events sent 3 real seconds apart, at the wire, BOTH at once — silently
  // defeating the entire point of live streaming, confirmed by comparing
  // real event timestamps from a direct backend request (properly
  // 3-second-spaced) against the same request through this proxy
  // (bunched). Next.js has no per-route compression toggle, so this is
  // global — an accepted bandwidth trade-off for correct real-time
  // delivery. A production deployment with its own edge/reverse proxy
  // (nginx, a CDN) in front can reintroduce compression there, correctly
  // configured to not buffer streaming routes.
  compress: false,
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
