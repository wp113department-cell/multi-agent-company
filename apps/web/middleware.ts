import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/auth/login", "/api/auth/setup"];

const isDev = process.env.NODE_ENV !== "production";

/**
 * Sol A44 (2026-10-13): Content-Security-Policy with a fresh nonce per
 * request. In production only scripts carrying this request's nonce run
 * ('strict-dynamic' lets them load the app's own chunks), so script-src no
 * longer needs 'unsafe-inline'. `next dev` keeps the looser policy: Fast
 * Refresh needs eval and inline scripts. Inline *styles* stay allowed
 * (Tailwind and next/font inject them).
 */
function contentSecurityPolicy(nonce: string): string {
  const scriptSrc = isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`;
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "img-src 'self' data: blob:",
    "object-src 'none'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "connect-src 'self'",
  ].join("; ");
}

export function middleware(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  // Next.js reads the nonce from the request's CSP header and adds it to
  // the scripts it renders.
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = route(request, requestHeaders);
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

function route(request: NextRequest, requestHeaders: Headers): NextResponse {
  const { pathname } = request.nextUrl;
  const next = () => NextResponse.next({ request: { headers: requestHeaders } });

  // Allow public paths and static assets
  if (
    PUBLIC_PATHS.some((p) => pathname.startsWith(p)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    return next();
  }

  // Check for JWT in Authorization header (API calls) or cookie
  const authHeader = request.headers.get("authorization");
  const rawCookie = request.cookies.get("gridiron_token")?.value;
  // Cookie is URI-encoded by the client (encodeURIComponent); decode before checking
  const tokenCookie = rawCookie ? decodeURIComponent(rawCookie) : undefined;

  if (authHeader?.startsWith("Bearer ") || tokenCookie) {
    return next();
  }

  // For browser navigation (no auth header), redirect to login
  // Note: client-side pages check localStorage; middleware catches SSR/navigation
  // We only hard-redirect if it's a full page navigation (no accept: application/json)
  const acceptHeader = request.headers.get("accept") ?? "";
  if (acceptHeader.includes("text/html")) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
