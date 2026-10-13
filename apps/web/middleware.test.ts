// @vitest-environment node
/**
 * Sol A44 (2026-10-13): every response carries a Content-Security-Policy
 * with a fresh nonce; in production scripts need that nonce (no
 * 'unsafe-inline'), in development the looser policy Fast Refresh needs.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

async function load(env: string) {
  vi.resetModules();
  vi.stubEnv("NODE_ENV", env);
  return import("./middleware");
}

function request(path: string, cookie = true): NextRequest {
  const headers: Record<string, string> = { accept: "text/html" };
  if (cookie) headers.cookie = "gridiron_token=abc";
  return new NextRequest(`http://localhost:3000${path}`, { headers });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Content-Security-Policy", () => {
  it("in production, scripts need this request's nonce", async () => {
    const { middleware } = await load("production");
    const first = middleware(request("/tasks")).headers.get("Content-Security-Policy")!;
    const second = middleware(request("/tasks")).headers.get("Content-Security-Policy")!;
    expect(first).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
    expect(first).not.toContain("'unsafe-inline' 'unsafe-eval'");
    expect(first.match(/script-src[^;]*/)![0]).not.toContain("unsafe-inline");
    expect(first).not.toBe(second); // a new nonce every time
  });

  it("redirects to login carry the policy too", async () => {
    const { middleware } = await load("production");
    const res = middleware(request("/tasks", false));
    expect(res.status).toBe(307);
    expect(res.headers.get("Content-Security-Policy")).toContain("nonce-");
  });

  it("in development, Fast Refresh still works", async () => {
    const { middleware } = await load("development");
    const csp = middleware(request("/tasks")).headers.get("Content-Security-Policy")!;
    expect(csp).toContain("'unsafe-eval'");
  });
});
