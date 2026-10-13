import { afterEach, describe, expect, it, vi } from "vitest";
import {
  approveEpic,
  approveTaskPlan,
  createTask,
  deleteRepo,
  fetchTasks,
  redirectIfSessionExpired,
  updateTaskStatus,
} from "./api";

function mockFetchOk(body: unknown = {}): ReturnType<typeof vi.fn> {
  const mockFetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  });
  vi.stubGlobal("fetch", mockFetch);
  return mockFetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch (cookie-authenticated requests)", () => {
  it("does not expose a bearer credential on a GET request", async () => {
    const mockFetch = mockFetchOk({ tasks: [] });

    await fetchTasks();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).not.toHaveProperty("Authorization");
  });

  it("preserves JSON headers for POST and PATCH requests", async () => {
    const mockFetch = mockFetchOk({ id: 1 });

    await createTask({ title: "t", description: "d" });
    await updateTaskStatus("1", "completed");

    expect(mockFetch.mock.calls[0]![1]!.headers).toMatchObject({
      "Content-Type": "application/json",
    });
    expect(mockFetch.mock.calls[1]![1]!.headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });

  it("does not add an Authorization header to DELETE requests", async () => {
    const mockFetch = mockFetchOk({ deleted: true, id: 1 });

    await deleteRepo(1);

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).not.toHaveProperty("Authorization");
  });

  it("preserves endpoint-specific headers without a bearer token", async () => {
    const mockFetch = mockFetchOk({ epicId: "e1", status: "approved" });

    await approveEpic("e1", "user-1");

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ "X-User-Id": "user-1" });
    expect(init.headers).not.toHaveProperty("Authorization");
  });
});

describe("approveTaskPlan", () => {
  // Live-AI rehearsal 2026-10-05: the task page approved a waiting plan by
  // calling POST /run, which only starts planning and refuses ready_for_review.
  it("approves a waiting plan through /approve, never /run", async () => {
    const mockFetch = mockFetchOk({ triggered: true });

    await approveTaskPlan("42");

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/tasks\/42\/approve$/);
    expect(init.method).toBe("POST");
  });
});

describe("createTask priority (Sol A34)", () => {
  it.each(["low", "medium", "high"] as const)("sends priority %s to the backend", async (priority) => {
    const mockFetch = mockFetchOk({ id: 1 });
    await createTask({ title: "t", description: "d", priority });
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).priority).toBe(priority);
  });
});


describe("expired session (Sol A35)", () => {
  it("a 401 sends the user to login, keeping where they were", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/tasks", search: "?project=7", assign });
    redirectIfSessionExpired(401);
    expect(assign).toHaveBeenCalledWith("/login?expired=1&from=%2Ftasks%3Fproject%3D7");
  });

  it("other errors and the login page itself do not redirect", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/tasks", search: "", assign });
    redirectIfSessionExpired(403);
    redirectIfSessionExpired(500);
    vi.stubGlobal("location", { pathname: "/login", search: "", assign });
    redirectIfSessionExpired(401);
    expect(assign).not.toHaveBeenCalled();
  });
});
