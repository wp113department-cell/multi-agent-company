import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authHeaders,
  changePassword,
  clearToken,
  getRole,
  getToken,
  isApprover,
  isAuthenticated,
  login,
  syncAuthCookie,
} from "./auth";

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("cookie session auth", () => {
  it("never exposes a credential to JavaScript", () => {
    expect(getToken()).toBeNull();
    expect(authHeaders()).toEqual({});
  });

  it("uses non-sensitive role metadata for UI state", () => {
    localStorage.setItem("gridiron_role", "approver");

    expect(isAuthenticated()).toBe(true);
    expect(getRole()).toBe("approver");
    expect(isApprover()).toBe(true);
  });

  it("treats viewer metadata as non-approver", () => {
    localStorage.setItem("gridiron_role", "viewer");

    expect(isApprover()).toBe(false);
  });

  it("clears local metadata and requests server-side logout", () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    localStorage.setItem("gridiron_role", "approver");

    clearToken();

    expect(isAuthenticated()).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
  });

  it("does not synchronize a JavaScript-readable auth cookie", () => {
    syncAuthCookie();
    expect(document.cookie).not.toContain("gridiron_token");
  });
});

// Production audit 14 (REPRO-14-006): forced password change + error messages.
describe("login and password change", () => {
  const reply = (status: number, body: unknown) =>
    vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });

  it("reports when the account must change its password", async () => {
    vi.stubGlobal(
      "fetch",
      reply(200, { username: "admin", role: "admin", must_change_password: true }),
    );
    expect(await login("admin", "x")).toEqual({ ok: true, mustChangePassword: true });
  });

  it("shows the backend's own error message, not just the status code", async () => {
    vi.stubGlobal(
      "fetch",
      reply(401, { error: { code: "401", message: "Invalid username or password" } }),
    );
    expect(await login("admin", "bad")).toEqual({
      ok: false,
      error: "Invalid username or password",
    });
  });

  it("changes the password and surfaces a refusal", async () => {
    const ok = reply(200, { status: "changed" });
    vi.stubGlobal("fetch", ok);
    expect(await changePassword("old-pass-1", "new-pass-22")).toEqual({ ok: true });
    expect(ok).toHaveBeenCalledWith(
      "/api/auth/change-password",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ current_password: "old-pass-1", new_password: "new-pass-22" }),
      }),
    );
    vi.stubGlobal(
      "fetch",
      reply(401, { error: { code: "401", message: "Current password is incorrect" } }),
    );
    expect(await changePassword("wrong", "new-pass-22")).toEqual({
      ok: false,
      error: "Current password is incorrect",
    });
  });
});
