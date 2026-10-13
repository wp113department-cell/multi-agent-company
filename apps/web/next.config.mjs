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
    // Sol A44 (2026-10-13): Content-Security-Policy is set per request by
    // middleware.ts (it needs a fresh nonce each time); the other security
    // headers stay here.
    return [
      {
        source: "/(.*)",
        headers: [
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
