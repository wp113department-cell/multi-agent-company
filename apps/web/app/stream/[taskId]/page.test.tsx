import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ActivityFeedPage from "./page";

// Gap-closure Stage 1.4 (answers.md) — proves the SSE reconnect-with-backoff
// behavior actually works: before this, es.onerror unconditionally called
// es.close() on ANY connection error, which defeats EventSource's own
// native auto-reconnect and left a dropped connection permanently dead.
// A controllable fake EventSource (jsdom doesn't implement the real thing)
// lets this test fire onerror deliberately and assert a NEW connection is
// actually opened after the backoff delay — not just that the code compiles.
//
// vi.useFakeTimers() is active throughout, so every assertion uses
// vi.waitFor (not @testing-library/react's waitFor, which polls on real
// timers and deadlocks against a fake clock), and every FakeEventSource
// callback that triggers a React state update is wrapped in act().

vi.mock("next/navigation", () => ({
  useParams: () => ({ taskId: "task-1" }),
  useRouter: () => ({ back: vi.fn() }),
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

function getInstance(index: number): FakeEventSource {
  const instance = FakeEventSource.instances[index];
  if (!instance) {
    throw new Error(`Expected FakeEventSource.instances[${index}] to exist`);
  }
  return instance;
}

describe("ActivityFeedPage SSE reconnect-with-backoff", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    // jsdom doesn't implement scrollIntoView (used by the page's pre-existing
    // auto-scroll effect, unrelated to this test) — a well-known jsdom gap,
    // not something this change introduces.
    Element.prototype.scrollIntoView = vi.fn();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens exactly one connection on mount", async () => {
    render(<ActivityFeedPage />);
    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    expect(getInstance(0).url).toBe("/api/tasks/task-1/stream");
  });

  it("reconnects with backoff after a transient connection error", async () => {
    render(<ActivityFeedPage />);
    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBe(1));

    const first = getInstance(0);
    act(() => first.onopen?.());
    await vi.waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());

    // Simulate a dropped connection — no terminal event was ever received.
    act(() => first.onerror?.());
    expect(first.closed).toBe(true);

    // Both the status pill and the inline events-list message render this
    // text — the page intentionally shows the reconnect state in two places.
    await vi.waitFor(() =>
      expect(screen.getAllByText(/reconnecting \(attempt 1\/5\)/).length).toBeGreaterThan(0),
    );
    // Must not have reconnected yet — the backoff delay hasn't elapsed.
    expect(FakeEventSource.instances.length).toBe(1);

    await act(() => vi.advanceTimersByTimeAsync(1000));

    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBe(2));
    expect(getInstance(1).url).toBe("/api/tasks/task-1/stream");

    act(() => getInstance(1).onopen?.());
    await vi.waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  });

  it("does NOT reconnect after a genuine terminal event from the server", async () => {
    render(<ActivityFeedPage />);
    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBe(1));

    const first = getInstance(0);
    act(() => first.onopen?.());
    act(() =>
      first.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "done",
            summary: "finished",
            tokens_in: 10,
            tokens_out: 5,
            cost_usd: 0.01,
            ts: 0,
          }),
        }),
      ),
    );
    await vi.waitFor(() => expect(screen.getByText("done")).toBeInTheDocument());

    // A spurious onerror after the terminal event must not trigger a reconnect.
    act(() => first.onerror?.());
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(FakeEventSource.instances.length).toBe(1);
  });

  it("gives up after MAX_RECONNECT_ATTEMPTS and shows a real error state", async () => {
    render(<ActivityFeedPage />);
    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBe(1));

    for (let attempt = 0; attempt < 5; attempt++) {
      const current = getInstance(FakeEventSource.instances.length - 1);
      act(() => current.onerror?.());
      const delay = Math.min(1000 * 2 ** attempt, 30000);
      await act(() => vi.advanceTimersByTimeAsync(delay));
    }
    await vi.waitFor(() => expect(FakeEventSource.instances.length).toBe(6));

    // The 6th (final) attempt's error must give up, not schedule a 7th.
    act(() => getInstance(5).onerror?.());
    await vi.waitFor(() => expect(screen.getByText("error")).toBeInTheDocument());
    await act(() => vi.advanceTimersByTimeAsync(60000));
    expect(FakeEventSource.instances.length).toBe(6);
  });
});
