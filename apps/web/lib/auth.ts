"use client";

const ROLE_KEY = "gridiron_role";

export function getToken(): string | null {
  return null;
}

export function setToken(_token: string): void {
  // Session credentials are set as HttpOnly cookies by POST /api/auth/login.
}

export function clearToken(): void {
  if (typeof window !== "undefined") localStorage.removeItem(ROLE_KEY);
  void fetch("/api/auth/logout", { method: "POST" });
}

export function syncAuthCookie(): void {
  // Cookie sessions need no client-side synchronization.
}

export function isAuthenticated(): boolean {
  return typeof window !== "undefined" && Boolean(localStorage.getItem(ROLE_KEY));
}

export function authHeaders(): Record<string, string> {
  return {};
}

export function getRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ROLE_KEY);
}

/** Matches the backend's own require_approver check (role in ("approver", "admin")). */
export function isApprover(): boolean {
  const role = getRole();
  return role === "approver" || role === "admin";
}

export async function login(
  username: string,
  password: string,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, error: body.detail || `HTTP ${res.status}` };
    }
    const data = await res.json();
    if (data.username && typeof data.role === "string") {
      localStorage.setItem(ROLE_KEY, data.role);
      return { ok: true };
    }
    return { ok: false, error: "No token in response" };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export async function logout(): Promise<void> {
  if (typeof window !== "undefined") localStorage.removeItem(ROLE_KEY);
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  window.location.href = "/login";
}
