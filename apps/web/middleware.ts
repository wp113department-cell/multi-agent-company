import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/auth/login", "/api/auth/setup"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths and static assets
  if (
    PUBLIC_PATHS.some((p) => pathname.startsWith(p)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // Check for JWT in Authorization header (API calls) or cookie
  const authHeader = request.headers.get("authorization");
  const tokenCookie = request.cookies.get("gridiron_token")?.value;

  if (authHeader?.startsWith("Bearer ") || tokenCookie) {
    return NextResponse.next();
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

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
