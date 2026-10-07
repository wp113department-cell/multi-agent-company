import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TerminalPanel } from "./TerminalPanel";

// Q12/#3 — real interactive PTY terminal, frontend.
//
// Real end-to-end behavior (real browser, real WebSocket, real Docker-
// sandboxed shell, real keyboard Ctrl+C, tab-switch session persistence)
// was verified live with Playwright against the actual running dev stack
// before this file was written — see the T2-B9/#3 commit's own evidence.
// jsdom cannot host a real WebSocket or a real terminal's keyboard input
// stack, so this file covers what jsdom CAN exercise soundly: the
// connection URL, every server->client message type's handling, and the
// close-code -> user-facing-message mapping — mirroring this project's own
// established pattern (app/stream/[taskId]/page.test.tsx's FakeEventSource)
// of stubbing the real browser API rather than mocking the component.

// jsdom implements none of matchMedia, canvas, or ResizeObserver — xterm.js
// needs the first to construct at all (falls back gracefully without
// canvas, using its DOM renderer instead, confirmed live), and
// TerminalPanel's own auto-fit-on-resize needs the third.
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
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason: "" });
  }

  // Test helpers — not part of the real WebSocket API.
  simulateOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(obj: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }

  simulateServerClose(code: number, reason = "") {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason });
  }
}

function base64Of(text: string): string {
  return Buffer.from(text, "utf-8").toString("base64");
}

function lastInstance(): FakeWebSocket {
  const inst = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  if (!inst) throw new Error("Expected a FakeWebSocket instance to exist");
  return inst;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TerminalPanel", () => {
  it("opens a WebSocket to the correct same-origin URL for the chat session", () => {
    render(<TerminalPanel chatSessionId="session-abc-123" visible={true} />);
    const ws = lastInstance();
    expect(ws.url).toBe(`ws://${window.location.host}/api/terminal/ws/session-abc-123`);
  });

  it("shows Connecting, then Connected once the server sends 'ready'", async () => {
    render(<TerminalPanel chatSessionId="s1" visible={true} />);
    expect(screen.getByText(/Connecting/)).toBeInTheDocument();

    const ws = lastInstance();
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "ready", pty_session_id: "p1", container_name: "c1" });
    });

    await waitFor(() =>
      expect(screen.getByText(/Connected — real interactive shell/)).toBeInTheDocument(),
    );
  });

  it("sends the real terminal size immediately on open, not the stale default", () => {
    render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const ws = lastInstance();
    act(() => ws.simulateOpen());

    expect(ws.sent).toHaveLength(1);
    const msg = JSON.parse(ws.sent[0] as string);
    expect(msg.type).toBe("resize");
    expect(typeof msg.rows).toBe("number");
    expect(typeof msg.cols).toBe("number");
  });

  it("decodes and writes real base64 output from the server into the terminal", async () => {
    render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const ws = lastInstance();
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "ready" });
      ws.simulateMessage({ type: "output", data: base64Of("HELLO_FROM_FAKE_PTY") });
    });

    await waitFor(() =>
      expect(document.body.textContent).toContain("HELLO_FROM_FAKE_PTY"),
    );
  });

  it("shows a session-ended message and offers a New Terminal button on 'exited'", async () => {
    render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const ws = lastInstance();
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "ready" });
      ws.simulateMessage({ type: "exited", alive: false });
    });

    await waitFor(() => expect(screen.getByText(/Session ended/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /New Terminal/ })).toBeInTheDocument();
  });

  it.each([
    [4404, "turned off on this server"],
    [4004, "chat session has ended"],
    [4403, "Only approvers and admins"],
    [4503, "Docker is not reachable"],
  ])("maps close code %i to a clear user-facing message", async (code, expectedSubstring) => {
    render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const ws = lastInstance();
    act(() => ws.simulateServerClose(code));

    await waitFor(() =>
      expect(screen.getByText(new RegExp(expectedSubstring))).toBeInTheDocument(),
    );
  });

  it("treats a normal close (code 1000) from a connected session as a graceful end, not an error", async () => {
    render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const ws = lastInstance();
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "ready" });
      ws.simulateServerClose(1000);
    });

    await waitFor(() => expect(screen.getByText(/Session ended/)).toBeInTheDocument());
    expect(screen.queryByText(/Connection closed/)).not.toBeInTheDocument();
  });

  it("closes the WebSocket on unmount", () => {
    const { unmount } = render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const ws = lastInstance();
    const closeSpy = vi.spyOn(ws, "close");
    unmount();
    expect(closeSpy).toHaveBeenCalledWith(1000);
  });

  it("ignores a stale instance's late close event after a reconnect (React Strict Mode double-invoke)", async () => {
    // Regression test for a real bug found via manual Playwright testing:
    // Strict Mode's mount->cleanup->remount cycle left the FIRST (torn
    // down) WebSocket's own onclose (fired async, code 1006) able to
    // clobber the UI with a stale error after the SECOND, real connection
    // had already reported "connected".
    const { rerender } = render(<TerminalPanel chatSessionId="s1" visible={true} />);
    const firstWs = lastInstance();

    // Simulate Strict Mode's remount: a fresh mount creates a second
    // instance while the first is torn down (unmount is exercised via
    // rerender with a different key forcing a real remount).
    rerender(<TerminalPanel key="remount" chatSessionId="s1" visible={true} />);
    const secondWs = lastInstance();
    expect(secondWs).not.toBe(firstWs);

    act(() => {
      secondWs.simulateOpen();
      secondWs.simulateMessage({ type: "ready" });
    });
    await waitFor(() =>
      expect(screen.getByText(/Connected — real interactive shell/)).toBeInTheDocument(),
    );

    // The first, discarded instance's close event arrives late — it must
    // not be able to override the now-healthy connected state.
    act(() => firstWs.simulateServerClose(1006, ""));

    expect(screen.getByText(/Connected — real interactive shell/)).toBeInTheDocument();
    expect(screen.queryByText(/Connection closed/)).not.toBeInTheDocument();
  });
});
