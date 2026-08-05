import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authHeaders,
  clearToken,
  getRole,
  getToken,
  isApprover,
  isAuthenticated,
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
