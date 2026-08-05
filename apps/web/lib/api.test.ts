import { afterEach, describe, expect, it, vi } from "vitest";
import { approveEpic, createTask, deleteRepo, fetchTasks, updateTaskStatus } from "./api";

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
