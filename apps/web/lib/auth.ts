"use client";

const TOKEN_KEY = "gridiron_token";
const COOKIE_MAX_AGE = 60 * 60 * 24; // 24 hours (matches JWT_EXPIRE_MINUTES=1440)

function setCookie(value: string): void {
  document.cookie = `${TOKEN_KEY}=${encodeURIComponent(value)}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

function deleteCookie(): void {
  document.cookie = `${TOKEN_KEY}=; path=/; max-age=0; SameSite=Lax`;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  setCookie(token); // middleware reads this on server-side navigation
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  deleteCookie();
}

/** Call once on app boot — syncs cookie from localStorage for already-logged-in users. */
export function syncAuthCookie(): void {
  if (typeof window === "undefined") return;
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    setCookie(token);
  } else {
    deleteCookie();
  }
}

export function isAuthenticated(): boolean {
  return Boolean(getToken());
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Gap-closure Stage 1.4 (answers.md) — UI-level role gating. The server is
// the real enforcement point (app/middleware/rbac.py's own docstring:
// "UI hiding buttons is a courtesy only") — this exists purely so a
// viewer-role user doesn't see an Approve/Reject button that would just
// 403, not as a security boundary. Decodes the JWT's own `role` claim
// (already embedded by the backend's create_access_token({"sub", "role"})
// at login) client-side — no signature verification, since that would be
// meaningless here: a forged role claim still hits the real, signature-
// verified check server-side and gets a real 403, this only ever affects
// what's rendered.
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const payloadB64 = token.split(".")[1];
    if (!payloadB64) return null;
    const base64 = payloadB64.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function getRole(): string | null {
  const token = getToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  const role = payload?.role;
  return typeof role === "string" ? role : null;
}

/** Matches the backend's own require_approver check (role in ("approver", "admin")). */
export function isApprover(): boolean {
  const role = getRole();
  return role === "approver" || role === "admin";
}

export async function login(
  username: string,
  password: string
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
    if (data.access_token) {
      setToken(data.access_token);
      return { ok: true };
    }
    return { ok: false, error: "No token in response" };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export function logout(): void {
  clearToken();
  window.location.href = "/login";
}
