import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationBell, type TaskNotification } from "./NotificationBell";

// Production audit 08 (PROD-08-006): in-app failure alerts. The backend list
// (GET /api/notifications) is covered by
// backend/tests/test_audit08_in_app_notifications.py; this covers the bell's
// unread count, seen-state, list and new-alert toast.

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const item = (taskId: number, at: string, status = "blocked"): TaskNotification => ({
  taskId,
  title: `Task ${taskId}`,
  status,
  blockedReason: status === "blocked" ? "orphaned" : null,
  message: `Problem ${taskId}`,
  at,
});

function mockFetch(...responses: TaskNotification[][]) {
  const fn = vi.fn();
  for (const items of responses) {
    fn.mockResolvedValueOnce({ ok: true, json: async () => ({ items }) });
  }
  fn.mockResolvedValue({ ok: true, json: async () => ({ items: responses.at(-1) ?? [] }) });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders nothing and makes no request when signed out", () => {
    const fetchMock = mockFetch([]);
    const { container } = render(<NotificationBell authed={false} />);
    expect(container.firstChild).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the unread count, lists alerts, and clears unread when opened", async () => {
    mockFetch([
      item(2, "2026-10-02T10:00:00+00:00", "failed"),
      item(1, "2026-10-01T10:00:00+00:00"),
    ]);
    render(<NotificationBell authed />);
    expect(await screen.findByLabelText("Notifications, 2 unread")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Notifications, 2 unread"));
    expect(screen.getByText("Task 2")).toBeTruthy();
    expect(screen.getByText("Problem 1")).toBeTruthy();
    expect(screen.getByText("Task 1").closest("a")?.getAttribute("href")).toBe("/tasks/1");
    expect(screen.getByLabelText("Notifications")).toBeTruthy();
    expect(window.localStorage.getItem("gridiron_notifications_seen_at")).toBe(
      "2026-10-02T10:00:00+00:00",
    );
  });

  it("toasts a new alert that arrives while the app is open (not ones already there)", async () => {
    const old = item(1, "2026-10-01T10:00:00+00:00");
    const fresh = item(3, "2026-10-02T12:00:00+00:00", "failed");
    mockFetch([old], [fresh, old]);
    render(<NotificationBell authed />);
    await screen.findByLabelText("Notifications, 1 unread");
    expect(screen.queryByRole("status")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    const toast = await screen.findByRole("status");
    expect(toast.textContent).toContain("Task failed: Task 3");
  });
});
