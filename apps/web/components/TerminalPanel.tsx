"use client";

import { useEffect, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

// ---------------------------------------------------------------------------
// Q12/#3 — real interactive PTY terminal, frontend half.
//
// Wire protocol matches backend/app/api/terminal.py exactly:
//   client -> server: {"type":"input","data":"<base64>"} |
//                      {"type":"resize","rows":N,"cols":N} | {"type":"ctrl_c"}
//   server -> client: {"type":"ready", pty_session_id, container_name} |
//                      {"type":"output","data":"<base64>"} |
//                      {"type":"exited","alive":false} |
//                      {"type":"error","message":"..."}
//
// Output is base64 because a real shell's stdout is arbitrary bytes (ANSI
// control sequences, non-UTF-8 tool output) — text WebSocket frames must be
// valid Unicode. Decoded straight to a Uint8Array and handed to xterm's own
// write(), which parses raw bytes (UTF-8 + ANSI) the same way a real
// terminal emulator does — never round-tripped through a JS string, which
// would risk double-decoding multi-byte sequences.
//
// Ctrl+C needs no special wire message from here: xterm's own onData()
// already delivers the raw INTR byte (0x03) exactly as a real terminal
// driver would when the user presses Ctrl+C, so it flows through the same
// generic "input" path PtySession.write() already handles correctly.
// ---------------------------------------------------------------------------

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i] ?? 0);
  return btoa(binary);
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// Matches the close codes backend/app/api/terminal.py defines.
const CLOSE_REASONS: Record<number, string> = {
  4404: "Interactive terminals are disabled on this server (pty_terminal_enabled=false).",
  4004: "Chat session not found — start a chat session first.",
  4403: "Approver role required to open an interactive terminal.",
  4503: "Sandbox is unavailable (Docker unreachable) — cannot start a terminal.",
};

type ConnState = "connecting" | "connected" | "closed" | "error";

interface TerminalPanelProps {
  chatSessionId: string;
  /** Only mounted once the user first opens the Terminal tab — keeps
   * display:none/block toggling from destroying the live session, while
   * still not spinning up a Docker container for every chat session that
   * never opens one. */
  visible: boolean;
}

export function TerminalPanel({ chatSessionId, visible }: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const lastSizeRef = useRef<{ rows: number; cols: number }>({ rows: 0, cols: 0 });

  const [state, setState] = useState<ConnState>("connecting");
  const [message, setMessage] = useState<string | null>(null);
  // Bumping this re-runs the connection effect — the only way to open a
  // brand new session/container once the old one exited or errored.
  const [connectAttempt, setConnectAttempt] = useState(0);

  useEffect(() => {
    if (!containerRef.current) return;

    // React's Strict Mode (dev only) mounts, cleans up, and remounts every
    // effect once — live-verified this caused a real bug: the FIRST,
    // immediately-torn-down WebSocket's own `onclose` (code 1006, since it
    // never finished its handshake) fired asynchronously AFTER the SECOND,
    // real connection had already reported "connected", overwriting the UI
    // with a stale "Connection closed" message despite a healthy session.
    // Every event handler below checks `cancelled` before touching state,
    // so a torn-down instance's late-arriving events are inert.
    let cancelled = false;

    const term = new XTerm({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      theme: {
        background: "#0f172a", // matches the app's slate-900 dark surfaces
        foreground: "#e2e8f0",
      },
      scrollback: 5000,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/api/terminal/ws/${chatSessionId}`,
    );
    wsRef.current = ws;
    setState("connecting");
    setMessage(null);

    ws.onopen = () => {
      if (cancelled) return;
      // Send the real initial size immediately — the backend's own default
      // (24x80) is otherwise wrong for almost every real browser window.
      lastSizeRef.current = { rows: term.rows, cols: term.cols };
      ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
    };

    ws.onmessage = (ev) => {
      if (cancelled) return;
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "ready") {
        setState("connected");
      } else if (msg.type === "output" && typeof msg.data === "string") {
        term.write(base64ToBytes(msg.data));
      } else if (msg.type === "exited") {
        term.write("\r\n\x1b[33m[terminal session ended]\x1b[0m\r\n");
        setState("closed");
      } else if (msg.type === "error" && typeof msg.message === "string") {
        setMessage(msg.message);
      }
    };

    ws.onclose = (ev) => {
      if (cancelled) return;
      setState((prev) => (prev === "connected" ? "closed" : "error"));
      const reason = CLOSE_REASONS[ev.code];
      if (reason) setMessage(reason);
      else if (ev.code !== 1000) setMessage(ev.reason || `Connection closed (code ${ev.code})`);
    };

    ws.onerror = () => {
      if (cancelled) return;
      setState("error");
    };

    const onData = term.onData((data) => {
      if (cancelled || ws.readyState !== WebSocket.OPEN) return;
      const bytes = new TextEncoder().encode(data);
      ws.send(JSON.stringify({ type: "input", data: bytesToBase64(bytes) }));
    });

    const resizeObserver = new ResizeObserver(() => {
      if (cancelled || !visible) return;
      try {
        fit.fit();
      } catch {
        return;
      }
      const { rows, cols } = term;
      if (rows !== lastSizeRef.current.rows || cols !== lastSizeRef.current.cols) {
        lastSizeRef.current = { rows, cols };
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", rows, cols }));
        }
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      cancelled = true;
      resizeObserver.disconnect();
      onData.dispose();
      ws.close(1000);
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatSessionId, connectAttempt]);

  // Re-fit whenever the panel becomes visible again (a hidden div's
  // `display:none` reports a zero-size container, so the fit computed
  // while hidden would be wrong).
  useEffect(() => {
    if (visible && fitRef.current) {
      try {
        fitRef.current.fit();
      } catch {
        return;
      }
    }
  }, [visible]);

  return (
    <div
      className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 dark:border-slate-700"
      style={{ display: visible ? "flex" : "none" }}
    >
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <span className="flex items-center gap-1.5 text-xs text-slate-400">
          <span
            className={`h-2 w-2 rounded-full ${
              state === "connected"
                ? "bg-green-400"
                : state === "connecting"
                  ? "bg-amber-400 animate-pulse"
                  : "bg-red-400"
            }`}
          />
          {state === "connecting" && "Connecting…"}
          {state === "connected" && "Connected — real interactive shell (sandboxed)"}
          {state === "closed" && "Session ended"}
          {state === "error" && "Disconnected"}
        </span>
        {(state === "closed" || state === "error") && (
          <button
            onClick={() => setConnectAttempt((n) => n + 1)}
            className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800"
          >
            New Terminal
          </button>
        )}
      </div>
      {message && (
        <p className="border-b border-slate-800 bg-red-950/40 px-3 py-1.5 text-xs text-red-300">
          {message}
        </p>
      )}
      <div ref={containerRef} className="min-h-0 flex-1 p-2" />
    </div>
  );
}
