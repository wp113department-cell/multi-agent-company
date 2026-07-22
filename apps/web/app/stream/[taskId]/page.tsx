"use client";

/**
 * Activity Feed — Claude Code-like streaming view for a running agent task.
 *
 * Events rendered:
 *  thinking    → expandable "Agent is thinking..." block
 *  tool_call   → tool name + truncated input
 *  tool_result → result preview (green ok / red error)
 *  file_edit   → file path + action badge
 *  terminal    → command + output in mono block
 *  token_usage → running counter in sidebar
 *  stopped     → checkpoint badge + resume input
 *  done        → success banner
 *  error       → error banner
 *  agent_switch      → node-transition divider (Day 18 — pipeline streaming)
 *  approval_required → interactive "review needed" card (Day 18)
 *  ping        → ignored (keep-alive)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ActivityEvent =
  | { type: "thinking"; content: string; agent: string; ts: number }
  | { type: "tool_call"; tool: string; input: Record<string, unknown>; id: string; ts: number }
  | { type: "tool_result"; tool: string; preview: string; ok: boolean; id: string; ts: number }
  | { type: "file_edit"; path: string; action: string; ts: number }
  | { type: "terminal"; command: string; output: string; exit_code: number; ts: number }
  | { type: "token_usage"; tokens_in: number; tokens_out: number; cost_usd: number; ts: number }
  | { type: "stopped"; checkpoint_id: string; tokens_in: number; tokens_out: number; ts: number }
  | { type: "done"; summary: string; tokens_in: number; tokens_out: number; cost_usd: number; ts: number }
  | { type: "error"; message: string; recoverable: boolean; ts: number }
  | { type: "agent_switch"; agent: string; phase: string; ts: number }
  | { type: "approval_required"; thread_id: string; action: string; ts: number }
  | { type: "ping"; ts: number };

// ---------------------------------------------------------------------------
// Single event renderers
// ---------------------------------------------------------------------------

function ThinkingBlock({ event }: { event: Extract<ActivityEvent, { type: "thinking" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="event-block thinking-block">
      <button className="event-header" onClick={() => setOpen(o => !o)}>
        <span className="event-icon">🧠</span>
        <span className="event-label">{event.agent} thinking…</span>
        <span className="toggle-arrow">{open ? "▲" : "▼"}</span>
      </button>
      {open && <pre className="event-body">{event.content}</pre>}
    </div>
  );
}

function ToolCallBlock({ event }: { event: Extract<ActivityEvent, { type: "tool_call" }> }) {
  return (
    <div className="event-block tool-call-block">
      <span className="event-icon">🔧</span>
      <span className="event-label">Calling <code>{event.tool}</code></span>
      <pre className="event-body small">{JSON.stringify(event.input, null, 2).slice(0, 400)}</pre>
    </div>
  );
}

function ToolResultBlock({ event }: { event: Extract<ActivityEvent, { type: "tool_result" }> }) {
  return (
    <div className={`event-block tool-result-block ${event.ok ? "ok" : "err"}`}>
      <span className="event-icon">{event.ok ? "✅" : "❌"}</span>
      <span className="event-label"><code>{event.tool}</code> result</span>
      <pre className="event-body small">{event.preview}</pre>
    </div>
  );
}

function FileEditBlock({ event }: { event: Extract<ActivityEvent, { type: "file_edit" }> }) {
  const actionColor: Record<string, string> = {
    write_file: "#22c55e", edit_file: "#3b82f6", apply_patch: "#a855f7",
    delete_file: "#ef4444",
  };
  const color = actionColor[event.action] ?? "#6b7280";
  return (
    <div className="event-block file-edit-block">
      <span className="event-icon">📝</span>
      <span className="event-label">{event.path}</span>
      <span className="action-badge" style={{ background: color }}>{event.action.replace("_", " ")}</span>
    </div>
  );
}

function TerminalBlock({ event }: { event: Extract<ActivityEvent, { type: "terminal" }> }) {
  return (
    <div className="event-block terminal-block">
      <div className="terminal-header">
        <span className="event-icon">💻</span>
        <code className="terminal-cmd">{event.command}</code>
        <span className={`exit-badge ${event.exit_code === 0 ? "ok" : "err"}`}>
          exit {event.exit_code}
        </span>
      </div>
      <pre className="terminal-output">{event.output}</pre>
    </div>
  );
}

function DoneBlock({ event }: { event: Extract<ActivityEvent, { type: "done" }> }) {
  return (
    <div className="event-block done-block">
      <span className="event-icon">🎉</span>
      <strong>Done!</strong>
      <span className="token-pill">{event.tokens_in + event.tokens_out} tokens · ${event.cost_usd.toFixed(4)}</span>
      {event.summary && <p className="done-summary">{event.summary}</p>}
    </div>
  );
}

function ErrorBlock({ event }: { event: Extract<ActivityEvent, { type: "error" }> }) {
  return (
    <div className="event-block error-block">
      <span className="event-icon">🔴</span>
      <strong>Error:</strong> {event.message}
    </div>
  );
}

function AgentSwitchBlock({ event }: { event: Extract<ActivityEvent, { type: "agent_switch" }> }) {
  return (
    <div className="agent-switch-divider">
      <span className="event-icon">➡️</span>
      <span>
        <strong>{event.agent}</strong>
        {event.phase ? ` — ${event.phase}` : ""}
      </span>
    </div>
  );
}

function ApprovalRequiredBlock({
  event,
}: {
  event: Extract<ActivityEvent, { type: "approval_required" }>;
}) {
  return (
    <div className="event-block approval-block">
      <span className="event-icon">⏳</span>
      <span className="event-label">Approval needed — {event.action.replace("_", " ")}</span>
      <a className="approval-link" href="/approvals">
        Review in Approvals →
      </a>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ActivityFeedPage() {
  const params = useParams();
  const router = useRouter();
  const taskId = typeof params.taskId === "string" ? params.taskId : String(params.taskId ?? "");

  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [status, setStatus] = useState<"connecting" | "running" | "stopped" | "done" | "error">("connecting");
  const [tokenUsage, setTokenUsage] = useState<{ in: number; out: number; cost: number }>({ in: 0, out: 0, cost: 0 });
  const [stoppedCheckpoint, setStoppedCheckpoint] = useState("");
  const [resumeMsg, setResumeMsg] = useState("");
  const [resumeLoading, setResumeLoading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  // SSE subscription
  useEffect(() => {
    if (!taskId) return;
    setStatus("connecting");
    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    esRef.current = es;

    es.onopen = () => setStatus("running");

    es.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as ActivityEvent;
        if (event.type === "ping") return;

        setEvents(prev => [...prev, event]);

        if (event.type === "token_usage") {
          setTokenUsage({ in: event.tokens_in, out: event.tokens_out, cost: event.cost_usd });
        }
        if (event.type === "done") {
          setStatus("done");
          setTokenUsage({ in: event.tokens_in, out: event.tokens_out, cost: event.cost_usd });
          es.close();
        }
        if (event.type === "stopped") {
          setStatus("stopped");
          setStoppedCheckpoint(event.checkpoint_id);
          es.close();
        }
        if (event.type === "error") {
          setStatus("error");
          es.close();
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      if (status !== "done" && status !== "stopped") {
        setStatus("error");
      }
      es.close();
    };

    return () => {
      es.close();
    };
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleStop = useCallback(async () => {
    setStopping(true);
    try {
      await fetch(`/api/tasks/${taskId}/stop`, { method: "POST" });
    } finally {
      setStopping(false);
    }
  }, [taskId]);

  const handleResume = useCallback(async () => {
    setResumeLoading(true);
    try {
      await fetch(`/api/tasks/${taskId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: resumeMsg, files: [] }),
      });
      setResumeMsg("");
      setStatus("connecting");
      // Re-connect SSE
      const es = new EventSource(`/api/tasks/${taskId}/stream`);
      esRef.current = es;
      es.onopen = () => setStatus("running");
      es.onmessage = (e: MessageEvent) => {
        try {
          const event = JSON.parse(e.data) as ActivityEvent;
          if (event.type !== "ping") setEvents(prev => [...prev, event]);
          if (event.type === "done" || event.type === "stopped" || event.type === "error") {
            es.close();
          }
        } catch { /* ignore */ }
      };
    } finally {
      setResumeLoading(false);
    }
  }, [taskId, resumeMsg]);

  const renderEvent = (ev: ActivityEvent, idx: number) => {
    switch (ev.type) {
      case "thinking":    return <ThinkingBlock key={idx} event={ev} />;
      case "tool_call":   return <ToolCallBlock key={idx} event={ev} />;
      case "tool_result": return <ToolResultBlock key={idx} event={ev} />;
      case "file_edit":   return <FileEditBlock key={idx} event={ev} />;
      case "terminal":    return <TerminalBlock key={idx} event={ev} />;
      case "done":        return <DoneBlock key={idx} event={ev} />;
      case "error":       return <ErrorBlock key={idx} event={ev} />;
      case "agent_switch":      return <AgentSwitchBlock key={idx} event={ev} />;
      case "approval_required": return <ApprovalRequiredBlock key={idx} event={ev} />;
      default:            return null;
    }
  };

  return (
    <main className="feed-root">
      <style>{`
        .feed-root { display: flex; gap: 16px; padding: 16px; min-height: 100vh; font-family: inherit; }
        .feed-main { flex: 1; min-width: 0; }
        .feed-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
        .feed-title { font-size: 18px; font-weight: 700; }
        .status-pill { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .status-pill.connecting { background: #fef9c3; color: #92400e; }
        .status-pill.running    { background: #dcfce7; color: #166534; }
        .status-pill.stopped    { background: #fef3c7; color: #92400e; }
        .status-pill.done       { background: #d1fae5; color: #065f46; }
        .status-pill.error      { background: #fee2e2; color: #991b1b; }
        .stop-btn { margin-left: auto; padding: 6px 14px; border-radius: 6px; border: 1.5px solid #ef4444;
                    color: #ef4444; background: transparent; cursor: pointer; font-weight: 600; font-size: 13px; }
        .stop-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .events-list { display: flex; flex-direction: column; gap: 8px; }
        .event-block { border-radius: 8px; padding: 10px 14px; font-size: 13px;
                       border: 1px solid transparent; }
        .thinking-block { background: #f0f4ff; border-color: #c7d2fe; }
        .thinking-block .event-header { display: flex; align-items: center; gap: 8px;
                                         cursor: pointer; background: none; border: none; width: 100%;
                                         font-size: 13px; text-align: left; }
        .toggle-arrow { margin-left: auto; color: #6b7280; }
        .tool-call-block  { background: #f5f3ff; border-color: #ddd6fe; }
        .tool-result-block.ok  { background: #f0fdf4; border-color: #bbf7d0; }
        .tool-result-block.err { background: #fef2f2; border-color: #fecaca; }
        .file-edit-block  { background: #eff6ff; border-color: #bfdbfe;
                            display: flex; align-items: center; gap: 10px; }
        .terminal-block   { background: #1e1e2e; color: #cdd6f4; border-color: #313244; }
        .terminal-header  { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
        .terminal-cmd     { color: #a6e3a1; font-size: 12px; }
        .terminal-output  { font-size: 11px; color: #bac2de; white-space: pre-wrap; max-height: 180px; overflow: auto; }
        .done-block  { background: #f0fdf4; border-color: #86efac; display: flex;
                       align-items: center; gap: 10px; flex-wrap: wrap; }
        .error-block { background: #fef2f2; border-color: #fca5a5; }
        .agent-switch-divider { display: flex; align-items: center; gap: 8px; padding: 4px 2px;
                                 font-size: 12px; color: #6b7280; }
        .approval-block { background: #fffbeb; border-color: #fbbf24; display: flex;
                           align-items: center; gap: 10px; flex-wrap: wrap; }
        .approval-link { margin-left: auto; font-size: 12px; font-weight: 600; color: #b45309;
                          text-decoration: underline; }
        .event-icon  { font-size: 16px; flex-shrink: 0; }
        .event-label { font-weight: 500; }
        .event-body  { margin: 8px 0 0; font-family: monospace; font-size: 11px;
                       white-space: pre-wrap; background: rgba(0,0,0,0.04);
                       border-radius: 4px; padding: 6px 8px; max-height: 160px; overflow: auto; }
        .event-body.small { font-size: 10px; max-height: 100px; }
        .action-badge { padding: 2px 8px; border-radius: 4px; color: #fff; font-size: 11px; font-weight: 600; }
        .exit-badge.ok  { color: #22c55e; font-size: 11px; }
        .exit-badge.err { color: #ef4444; font-size: 11px; }
        .token-pill { padding: 2px 8px; border-radius: 12px; background: #e0f2fe; color: #0369a1;
                      font-size: 11px; }
        .done-summary { margin: 6px 0 0; font-size: 12px; color: #374151; width: 100%; }
        .feed-sidebar { width: 220px; flex-shrink: 0; }
        .sidebar-card { border-radius: 8px; padding: 14px; background: #f9fafb;
                        border: 1px solid #e5e7eb; margin-bottom: 12px; }
        .sidebar-card h3 { font-size: 12px; font-weight: 700; color: #6b7280;
                           text-transform: uppercase; letter-spacing: .05em; margin: 0 0 10px; }
        .token-row { display: flex; justify-content: space-between; font-size: 12px;
                     margin-bottom: 4px; }
        .token-val { font-weight: 700; font-variant-numeric: tabular-nums; }
        .resume-section { margin-top: 16px; padding: 14px; border-radius: 8px;
                          background: #fffbeb; border: 1.5px solid #fbbf24; }
        .resume-section h4 { margin: 0 0 8px; font-size: 13px; }
        .resume-input { width: 100%; border-radius: 6px; border: 1px solid #d1d5db;
                        padding: 8px; font-size: 13px; resize: vertical; min-height: 60px; }
        .resume-btn { margin-top: 8px; width: 100%; padding: 7px; border-radius: 6px;
                      background: #f59e0b; border: none; color: #fff; font-weight: 600;
                      cursor: pointer; font-size: 13px; }
        .resume-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        @media (prefers-color-scheme: dark) {
          .thinking-block { background: #1e1b4b; border-color: #4338ca; }
          .tool-call-block { background: #1e1b3a; border-color: #6d28d9; }
          .tool-result-block.ok { background: #052e16; border-color: #16a34a; }
          .tool-result-block.err { background: #450a0a; border-color: #dc2626; }
          .file-edit-block { background: #0c1a2e; border-color: #1d4ed8; }
          .done-block { background: #022c22; border-color: #15803d; }
          .error-block { background: #450a0a; border-color: #dc2626; }
          .agent-switch-divider { color: #9ca3af; }
          .approval-block { background: #292524; border-color: #d97706; }
          .approval-link { color: #fbbf24; }
          .event-body { background: rgba(255,255,255,0.06); }
          .sidebar-card { background: #111827; border-color: #374151; }
          .resume-section { background: #292524; border-color: #d97706; }
          .resume-input { background: #1f2937; border-color: #4b5563; color: #f9fafb; }
        }
      `}</style>

      <div className="feed-main">
        <div className="feed-header">
          <button onClick={() => router.back()} style={{ fontSize: 13, cursor: "pointer" }}>← Back</button>
          <h1 className="feed-title">Task {taskId} — Activity Feed</h1>
          <span className={`status-pill ${status}`}>{status}</span>
          {status === "running" && (
            <button className="stop-btn" onClick={handleStop} disabled={stopping}>
              {stopping ? "Stopping…" : "⏹ Stop"}
            </button>
          )}
        </div>

        <div className="events-list">
          {events.length === 0 && status === "connecting" && (
            <p style={{ color: "#9ca3af", fontSize: 13 }}>Connecting to event stream…</p>
          )}
          {events.map(renderEvent)}
          <div ref={bottomRef} />
        </div>

        {status === "stopped" && (
          <div className="resume-section">
            <h4>⏸ Agent stopped (checkpoint: {stoppedCheckpoint})</h4>
            <p style={{ fontSize: 12, color: "#78716c", margin: "0 0 8px" }}>
              Send a message to resume the agent from where it stopped.
            </p>
            <textarea
              className="resume-input"
              placeholder="Type a message or instruction to inject…"
              value={resumeMsg}
              onChange={e => setResumeMsg(e.target.value)}
            />
            <button className="resume-btn" onClick={handleResume} disabled={resumeLoading}>
              {resumeLoading ? "Resuming…" : "▶ Resume"}
            </button>
          </div>
        )}
      </div>

      <aside className="feed-sidebar">
        <div className="sidebar-card">
          <h3>Token Usage</h3>
          <div className="token-row">
            <span>Input</span>
            <span className="token-val">{tokenUsage.in.toLocaleString()}</span>
          </div>
          <div className="token-row">
            <span>Output</span>
            <span className="token-val">{tokenUsage.out.toLocaleString()}</span>
          </div>
          <div className="token-row" style={{ borderTop: "1px solid #e5e7eb", paddingTop: 6, marginTop: 4 }}>
            <span>Cost</span>
            <span className="token-val">${tokenUsage.cost.toFixed(4)}</span>
          </div>
        </div>

        <div className="sidebar-card">
          <h3>Events</h3>
          <div className="token-row">
            <span>Total</span>
            <span className="token-val">{events.length}</span>
          </div>
          <div className="token-row">
            <span>Tool calls</span>
            <span className="token-val">{events.filter(e => e.type === "tool_call").length}</span>
          </div>
          <div className="token-row">
            <span>File edits</span>
            <span className="token-val">{events.filter(e => e.type === "file_edit").length}</span>
          </div>
        </div>
      </aside>
    </main>
  );
}
