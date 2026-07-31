import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "./auth";
import {
  approveEpic,
  createTask,
  deleteRepo,
  fetchTasks,
  updateTaskStatus,
} from "./api";

// Gap-closure Stage 1.4 (answers.md) — proves authHeaders() is now actually
// threaded through lib/api.ts's fetch calls via the shared apiFetch()
// wrapper. Before this, none of the 44 functions in this file sent the
// Authorization header the backend's RBAC middleware reads (only one
// unrelated page, app/repo/page.tsx, ever did it manually) — under
// RBAC_ENABLED=true every one of these calls would have failed with a 401,
// GET reads included, not just the mutating writes the plan named.

function mockFetchOk(body: unknown = {}): ReturnType<typeof vi.fn> {
  const mockFetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  });
  vi.stubGlobal("fetch", mockFetch);
  return mockFetch;
}

afterEach(() => {
  localStorage.clear();
  document.cookie = "gridiron_token=; path=/; max-age=0";
  vi.unstubAllGlobals();
});

describe("apiFetch (via lib/api.ts's exported functions)", () => {
  it("attaches the Authorization header on a GET read call when a token is set", async () => {
    const mockFetch = mockFetchOk({ tasks: [] });
    setToken("abc123");

    await fetchTasks();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ Authorization: "Bearer abc123" });
  });

  it("attaches the Authorization header on a mutating POST call when a token is set", async () => {
    const mockFetch = mockFetchOk({ id: 1 });
    setToken("abc123");

    await createTask({ title: "t", description: "d" });

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({
      Authorization: "Bearer abc123",
      "Content-Type": "application/json",
    });
  });

  it("attaches the Authorization header on a mutating PATCH call", async () => {
    const mockFetch = mockFetchOk({ id: 1 });
    setToken("abc123");

    await updateTaskStatus("1", "completed");

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ Authorization: "Bearer abc123" });
  });

  it("attaches the Authorization header on a mutating DELETE call", async () => {
    const mockFetch = mockFetchOk({ deleted: true, id: 1 });
    setToken("abc123");

    await deleteRepo(1);

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ Authorization: "Bearer abc123" });
  });

  it("attaches the Authorization header even on calls with their own custom headers", async () => {
    const mockFetch = mockFetchOk({ epicId: "e1", status: "approved" });
    setToken("abc123");

    await approveEpic("e1", "user-1");

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({
      Authorization: "Bearer abc123",
      "X-User-Id": "user-1",
    });
  });

  it("sends no Authorization header when no token is set (unchanged prior behavior)", async () => {
    const mockFetch = mockFetchOk({ tasks: [] });

    await fetchTasks();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).not.toHaveProperty("Authorization");
  });
});
