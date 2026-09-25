import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TerminalTabs } from "./TerminalTabs";

// #5 — multiple independent terminal tabs.
//
// Real multi-process independence (two tabs never share shell state, e.g.
// an exported env var in one is invisible in the other) and real
// kill-one-leave-others-alive behavior were verified live with Playwright
// against the actual running dev stack (real backend, real Docker) before
// this file was written. jsdom/FakeWebSocket here covers what a unit test
// can soundly assert: each tab gets its OWN WebSocket instance/connection,
// closing one tab's WebSocket never touches another tab's, and the tab bar
// itself (add/close/active-fallback) behaves correctly.

beforeEach(() => {
  window.matchMedia =
    window.matchMedia ||
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList);

  class FakeResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
});

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  closeCallCount = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send() {}

  close(code = 1000) {
    this.closeCallCount++;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason: "" });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

describe("TerminalTabs", () => {
  it("starts with exactly one tab, labeled Terminal 1", () => {
    render(<TerminalTabs chatSessionId="s1" visible={true} />);
    expect(screen.getByRole("tab", { name: "Terminal 1" })).toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("clicking + opens a new, independently-connected tab", () => {
    render(<TerminalTabs chatSessionId="s1" visible={true} />);
    act(() => screen.getByRole("button", { name: "New terminal" }).click());

    expect(screen.getByRole("tab", { name: "Terminal 1" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Terminal 2" })).toBeInTheDocument();
    // Each tab is its own TerminalPanel -> its own real WebSocket connection.
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[0]).not.toBe(FakeWebSocket.instances[1]);
  });

  it("closing one tab does not touch another tab's WebSocket at all", () => {
    render(<TerminalTabs chatSessionId="s1" visible={true} />);
    act(() => screen.getByRole("button", { name: "New terminal" }).click());
    expect(FakeWebSocket.instances).toHaveLength(2);
    const [ws1, ws2] = FakeWebSocket.instances;

    act(() => screen.getByRole("button", { name: "Close Terminal 2" }).click());

    expect(screen.queryByRole("tab", { name: "Terminal 2" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Terminal 1" })).toBeInTheDocument();
    // Closing tab 2 must close ONLY ws2 — ws1 (tab 1's real session) is
    // completely unaffected, proving kill-one-leave-others-alive at the
    // component level.
    expect(ws2?.closeCallCount).toBeGreaterThan(0);
    expect(ws1?.closeCallCount).toBe(0);
  });

  it("falls back to another open tab when the active tab is closed", () => {
    render(<TerminalTabs chatSessionId="s1" visible={true} />);
    act(() => screen.getByRole("button", { name: "New terminal" }).click());
    // Newly-added tab becomes active.
    expect(screen.getByRole("tab", { name: "Terminal 2" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    act(() => screen.getByRole("button", { name: "Close Terminal 2" }).click());

    expect(screen.getByRole("tab", { name: "Terminal 1" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows an empty state with a New Terminal button once every tab is closed", () => {
    render(<TerminalTabs chatSessionId="s1" visible={true} />);
    act(() => screen.getByRole("button", { name: "Close Terminal 1" }).click());

    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ New Terminal" })).toBeInTheDocument();
  });

  it("numbers new tabs incrementally even after earlier ones are closed", () => {
    render(<TerminalTabs chatSessionId="s1" visible={true} />);
    act(() => screen.getByRole("button", { name: "Close Terminal 1" }).click());
    act(() => screen.getByRole("button", { name: "+ New Terminal" }).click());

    // Matches the real Playwright-verified behavior: closed tab numbers are
    // never reused, avoiding a confusing "Terminal 1" reappearing for what
    // is actually a brand new, unrelated session.
    expect(screen.getByRole("tab", { name: "Terminal 2" })).toBeInTheDocument();
  });

  it("hides the whole panel (display:none) when not visible, without unmounting tabs", () => {
    const { container } = render(<TerminalTabs chatSessionId="s1" visible={false} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.style.display).toBe("none");
    // Still exactly one live WebSocket underneath — hidden, not torn down.
    // getByRole correctly can't see it (display:none removes it from the
    // accessibility tree, matching real browser behavior), so this checks
    // the actual DOM content is still there instead.
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(container.textContent).toContain("Terminal 1");
  });
});
