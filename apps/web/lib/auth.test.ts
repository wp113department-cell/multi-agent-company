import { afterEach, describe, expect, it } from "vitest";
import {
  authHeaders,
  clearToken,
  getToken,
  isAuthenticated,
  setToken,
  syncAuthCookie,
} from "./auth";

function readCookie(): string {
  return document.cookie;
}

afterEach(() => {
  localStorage.clear();
  document.cookie = "gridiron_token=; path=/; max-age=0";
});

describe("getToken / setToken / clearToken", () => {
  it("returns null when nothing is stored", () => {
    expect(getToken()).toBeNull();
  });

  it("returns the token after setToken", () => {
    setToken("abc123");
    expect(getToken()).toBe("abc123");
  });

  it("also writes a cookie so server-side navigation can read it", () => {
    setToken("abc123");
    expect(readCookie()).toContain("gridiron_token=abc123");
  });

  it("removes both localStorage and the cookie after clearToken", () => {
    setToken("abc123");
    clearToken();
    expect(getToken()).toBeNull();
    expect(readCookie()).not.toContain("abc123");
  });
});

describe("isAuthenticated", () => {
  it("is false with no token", () => {
    expect(isAuthenticated()).toBe(false);
  });

  it("is true once a token is set", () => {
    setToken("abc123");
    expect(isAuthenticated()).toBe(true);
  });
});

describe("authHeaders", () => {
  it("returns an empty object with no token", () => {
    expect(authHeaders()).toEqual({});
  });

  it("returns a Bearer Authorization header with a token", () => {
    setToken("abc123");
    expect(authHeaders()).toEqual({ Authorization: "Bearer abc123" });
  });
});

describe("syncAuthCookie", () => {
  it("writes the cookie from localStorage when a token exists", () => {
    localStorage.setItem("gridiron_token", "from-storage");
    syncAuthCookie();
    expect(readCookie()).toContain("gridiron_token=from-storage");
  });

  it("clears the cookie when localStorage has no token", () => {
    document.cookie = "gridiron_token=stale; path=/";
    syncAuthCookie();
    expect(readCookie()).not.toContain("stale");
  });
});
