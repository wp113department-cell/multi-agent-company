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
