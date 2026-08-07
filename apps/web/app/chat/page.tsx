"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { confirmChatAction, createChatSession, deleteChatSession, listRepos } from "@/lib/api";
import type { RepoRecord } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SseEvent =
  | { type: "thinking"; iteration: number }
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; tool_name: string; tool_input: Record<string, unknown>; tool_use_id: string }
  | { type: "tool_result"; tool_name: string; output: string; tool_use_id: string }
  | { type: "confirmation_required"; actionId: string; description: string; details: string }
  | { type: "done" }
  | { type: "error"; message: string };

interface TextMessage {
  role: "user" | "assistant";
  kind: "text";
  id: string;
  content: string;
}

interface ToolCallMessage {
  role: "assistant";
  kind: "tool_call";
  id: string;
  tool_use_id: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  output?: string;
  expanded: boolean;
}

interface ConfirmMessage {
  role: "system";
  kind: "confirm";
  id: string;
  actionId: string;
  description: string;
  details: string;
  resolved?: boolean;
  answer?: boolean;
}

type ChatMessage = TextMessage | ToolCallMessage | ConfirmMessage;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uid() {
  return Math.random().toString(36).slice(2);
}

function toolBadgeColor(name: string): string {
  if (name.startsWith("git_")) return "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300";
  if (name.startsWith("run_")) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  if (name === "bash") return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
  if (["write_file", "edit_file", "delete_file", "append_file"].includes(name))
    return "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300";
  return "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300";
}

function formatToolInput(input: Record<string, unknown>): string {
  try {
    return JSON.stringify(input, null, 2);
  } catch {
    return String(input);
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AssistantText({ content }: { content: string }) {
  // Simple markdown: code blocks and inline code
  const parts = content.split(/(```[\s\S]*?```|`[^`]+`)/g);
  return (
    <div className="whitespace-pre-wrap text-sm leading-relaxed">
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          const lines = part.slice(3).split("\n");
          const lang = (lines[0] ?? "").trim();
          const code = lines.slice(1).join("\n").replace(/```$/, "").trim();
          return (
            <pre key={i} className="my-2 overflow-x-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
              {lang && <span className="text-slate-400 text-[10px] block mb-1">{lang}</span>}
              <code>{code}</code>
            </pre>
          );
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={i} className="rounded bg-slate-200 px-1 py-0.5 text-xs dark:bg-slate-700">
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </div>
  );
}

function ToolCallBlock({ msg, onToggle }: { msg: ToolCallMessage; onToggle: () => void }) {
  const hasResult = msg.output !== undefined;
  return (
    <div className="my-1 rounded-lg border border-slate-200 bg-white text-sm dark:border-slate-700 dark:bg-slate-800">
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-700/50 rounded-lg"
      >
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold ${toolBadgeColor(msg.tool_name)}`}>
          {msg.tool_name}
        </span>
        {!hasResult && (
          <span className="ml-auto flex h-3 w-3 items-center">
            <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
          </span>
        )}
        {hasResult && (
          <span className="ml-auto text-xs text-slate-400">{msg.expanded ? "▲ hide" : "▼ show"}</span>
        )}
      </button>
      {msg.expanded && (
        <div className="border-t border-slate-100 dark:border-slate-700 px-3 pb-3 pt-2 space-y-2">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Input</p>
            <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-[11px] dark:bg-slate-900 dark:text-slate-300">
              {formatToolInput(msg.tool_input)}
            </pre>
          </div>
          {msg.output !== undefined && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Output</p>
              <pre className="max-h-64 overflow-y-auto overflow-x-auto rounded bg-slate-50 p-2 text-[11px] dark:bg-slate-900 dark:text-slate-300">
                {msg.output || "(empty)"}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ConfirmBlock({
  msg,
  onConfirm,
}: {
  msg: ConfirmMessage;
  onConfirm: (actionId: string, approved: boolean) => void;
}) {
  if (msg.resolved) {
    return (
      <div className="my-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800">
        <span className={`font-medium ${msg.answer ? "text-green-600" : "text-red-500"}`}>
          {msg.answer ? "✓ Approved" : "✕ Denied"}:
        </span>{" "}
        <span className="text-slate-600 dark:text-slate-400">{msg.description}</span>
      </div>
    );
  }

  return (
    <div className="my-2 rounded-xl border-2 border-amber-300 bg-amber-50 p-4 dark:border-amber-600 dark:bg-amber-900/20">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-lg">⚠️</span>
        <span className="font-semibold text-amber-800 dark:text-amber-200">{msg.description}</span>
      </div>
      <pre className="mb-3 overflow-x-auto rounded bg-amber-100 p-2 text-xs text-amber-900 dark:bg-amber-900/40 dark:text-amber-100">
        {msg.details}
      </pre>
      <div className="flex gap-2">
        <button
          onClick={() => onConfirm(msg.actionId, true)}
          className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700"
        >
          Approve
        </button>
        <button
          onClick={() => onConfirm(msg.actionId, false)}
          className="rounded-lg border border-red-300 px-4 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
        >
          Deny
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function ChatPage() {
  const [repos, setRepos] = useState<RepoRecord[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [customPath, setCustomPath] = useState<string>("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [reconnecting, setReconnecting] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reachedTerminalRef = useRef(false);

  // Streaming-turn state shared between the initial fetch-based reader and
  // a reconnect (GET /stream, EventSource-based — a POST body can't be
  // resent to reattach without re-running the agent). Refs, not locals,
  // since a reconnect can pick up mid-turn after sendMessage's closure
  // has already returned.
  const assistantMsgIdRef = useRef<string>(uid());
  const assistantContentRef = useRef<string>("");
  const hasAssistantMsgRef = useRef(false);

  // Load repos on mount
  useEffect(() => {
    listRepos()
      .then((data) => {
        setRepos(data.repos.filter((r) => r.status === "ready"));
        const active = data.repos.find((r) => r.isActive);
        if (active) setSelectedRepo(active.localPath);
      })
      .catch(() => {});
  }, []);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const repoPath = selectedRepo || customPath;

  // ---- Session management ----
  const startSession = useCallback(async () => {
    if (!repoPath) return;
    try {
      const data = await createChatSession(repoPath);
      setSessionId(data.session_id);
      setMessages([]);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [repoPath]);

  const endSession = useCallback(async () => {
    if (!sessionId) return;
    reachedTerminalRef.current = true;
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    esRef.current?.close();
    esRef.current = null;
    abortRef.current?.abort();
    await deleteChatSession(sessionId).catch(() => {});
    setSessionId(null);
    setMessages([]);
    setStreaming(false);
    setReconnecting(false);
  }, [sessionId]);

  // Unmount safety — mirrors the task activity feed's cleanup.
  useEffect(() => {
    return () => {
      reachedTerminalRef.current = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      esRef.current?.close();
    };
  }, []);

  // ---- Confirmation handler ----
  const handleConfirm = useCallback(
    async (actionId: string, approved: boolean) => {
      if (!sessionId) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.kind === "confirm" && m.actionId === actionId
            ? { ...m, resolved: true, answer: approved }
            : m,
        ),
      );
      try {
        await confirmChatAction(sessionId, actionId, approved);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [sessionId],
  );

  // ---- Toggle tool call expanded ----
  const toggleTool = useCallback((id: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.kind === "tool_call" && m.id === id ? { ...m, expanded: !m.expanded } : m,
      ),
    );
  }, []);

  const MAX_RECONNECT_ATTEMPTS = 5;
  const BASE_RECONNECT_DELAY_MS = 1000;

  // ---- Shared SSE event handling (initial fetch-stream + reconnect EventSource) ----
  const handleSseEvent = useCallback((event: SseEvent) => {
    if (event.type === "text_delta") {
      assistantContentRef.current += event.text;
      const id = assistantMsgIdRef.current;
      const content = assistantContentRef.current;
      setMessages((prev) =>
        prev.map((m) => (m.id === id && m.kind === "text" ? { ...m, content } : m)),
      );
    } else if (event.type === "tool_call") {
      if (assistantContentRef.current.trim()) {
        assistantMsgIdRef.current = uid();
        assistantContentRef.current = "";
      } else if (hasAssistantMsgRef.current) {
        const staleId = assistantMsgIdRef.current;
        setMessages((prev) => prev.filter((m) => m.id !== staleId));
        hasAssistantMsgRef.current = false;
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          kind: "tool_call",
          id: uid(),
          tool_use_id: event.tool_use_id,
          tool_name: event.tool_name,
          tool_input: event.tool_input,
          expanded: false,
        } satisfies ToolCallMessage,
      ]);

      assistantMsgIdRef.current = uid();
      assistantContentRef.current = "";
      hasAssistantMsgRef.current = false;
    } else if (event.type === "tool_result") {
      setMessages((prev) =>
        prev.map((m) =>
          m.kind === "tool_call" && m.tool_use_id === event.tool_use_id
            ? { ...m, output: event.output, expanded: true }
            : m,
        ),
      );
    } else if (event.type === "thinking") {
      if (!hasAssistantMsgRef.current) {
        assistantMsgIdRef.current = uid();
        assistantContentRef.current = "";
        const id = assistantMsgIdRef.current;
        setMessages((prev) => [
          ...prev,
          { role: "assistant", kind: "text", id, content: "" } satisfies TextMessage,
        ]);
        hasAssistantMsgRef.current = true;
      }
    } else if (event.type === "confirmation_required") {
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          kind: "confirm",
          id: uid(),
          actionId: event.actionId,
          description: event.description,
          details: event.details,
          resolved: false,
        } satisfies ConfirmMessage,
      ]);
    } else if (event.type === "done") {
      reachedTerminalRef.current = true;
      if (hasAssistantMsgRef.current && !assistantContentRef.current.trim()) {
        const staleId = assistantMsgIdRef.current;
        setMessages((prev) => prev.filter((m) => m.id !== staleId));
      }
    } else if (event.type === "error") {
      reachedTerminalRef.current = true;
      setError(event.message);
      if (hasAssistantMsgRef.current && !assistantContentRef.current.trim()) {
        const staleId = assistantMsgIdRef.current;
        setMessages((prev) => prev.filter((m) => m.id !== staleId));
      }
    }
  }, []);

  // ---- Reconnect to a dropped stream ----
  // The agent runs as a backend background task decoupled from the HTTP
  // connection that started it (backend/app/api/chat.py::send_message) — a
  // dropped fetch stream doesn't stop the agent mid-turn, it only stops
  // delivery of its events. Re-attach via GET /stream (EventSource-
  // compatible, unlike the POST that starts a turn) with capped exponential
  // backoff, same shape as the task activity feed's proven reconnect
  // (app/stream/[taskId]/page.tsx).
  const reconnect = useCallback(
    (activeSessionId: string, attempt: number) => {
      setReconnecting(true);
      setReconnectAttempt(attempt);

      const es = new EventSource(`/api/chat/sessions/${activeSessionId}/stream`);
      esRef.current = es;

      es.onopen = () => {
        setReconnecting(false);
        setReconnectAttempt(0);
      };

      es.onmessage = (e: MessageEvent) => {
        let event: SseEvent;
        try {
          event = JSON.parse(e.data) as SseEvent;
        } catch {
          return;
        }
        handleSseEvent(event);
        if (event.type === "done" || event.type === "error") {
          es.close();
          esRef.current = null;
          setStreaming(false);
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (reachedTerminalRef.current) {
          setReconnecting(false);
          setStreaming(false);
          return;
        }
        if (attempt >= MAX_RECONNECT_ATTEMPTS) {
          setReconnecting(false);
          setStreaming(false);
          setError("Lost connection to the agent's response stream and could not reconnect.");
          return;
        }
        const nextAttempt = attempt + 1;
        setReconnectAttempt(nextAttempt);
        const delay = Math.min(BASE_RECONNECT_DELAY_MS * 2 ** attempt, 30000);
        reconnectTimeoutRef.current = setTimeout(() => reconnect(activeSessionId, nextAttempt), delay);
      };
    },
    [handleSseEvent],
  );

  // ---- Send message ----
  const sendMessage = useCallback(async () => {
    if (!input.trim() || !sessionId || streaming) return;

    const userText = input.trim();
    setInput("");
    setError(null);
    setStreaming(true);
    reachedTerminalRef.current = false;

    // Add user message immediately
    setMessages((prev) => [
      ...prev,
      { role: "user", kind: "text", id: uid(), content: userText } satisfies TextMessage,
    ]);

    const abortCtrl = new AbortController();
    abortRef.current = abortCtrl;

    // Set once the turn is actually dispatched server-side (session.active
    // flips true before the response streams back) — only then is a dropped
    // connection safe to treat as reconnectable instead of a hard failure.
    let dispatched = false;
    let dispatchedReconnect = false;

    try {
      const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ message: userText }),
        signal: abortCtrl.signal,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as Record<string, unknown>;
        const detail = body?.detail;
        throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
      }

      if (!res.body) throw new Error("No response body");
      dispatched = true;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      assistantMsgIdRef.current = uid();
      assistantContentRef.current = "";

      // Add placeholder for streaming text
      setMessages((prev) => [
        ...prev,
        { role: "assistant", kind: "text", id: assistantMsgIdRef.current, content: "" } satisfies TextMessage,
      ]);
      hasAssistantMsgRef.current = true;

      let buffer = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          let event: SseEvent;
          try {
            event = JSON.parse(jsonStr) as SseEvent;
          } catch {
            continue;
          }

          handleSseEvent(event);
        }
        if (reachedTerminalRef.current) break;
      }
    } catch (e: unknown) {
      if ((e as Error).name === "AbortError") return;

      if (dispatched && !reachedTerminalRef.current) {
        dispatchedReconnect = true;
        reconnect(sessionId, 0);
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!dispatchedReconnect) {
        setStreaming(false);
      }
      abortRef.current = null;
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [input, sessionId, streaming, handleSseEvent, reconnect]);

  // Keyboard: Ctrl+Enter or Enter to send
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-[calc(100vh-120px)] flex-col">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Chat Agent</h1>
          <p className="text-sm text-slate-500">
            Conversational AI coding assistant — reads, writes, debugs, commits
          </p>
        </div>
        {sessionId && (
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              <span className={`h-2 w-2 rounded-full ${reconnecting ? "bg-amber-400 animate-pulse" : "bg-green-400"}`} />
              {reconnecting
                ? `Reconnecting… (attempt ${reconnectAttempt}/${MAX_RECONNECT_ATTEMPTS})`
                : `Connected · ${repoPath.split("/").slice(-2).join("/")}`}
            </span>
            <button
              onClick={() => void endSession()}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400"
            >
              End Session
            </button>
          </div>
        )}
      </div>

      {/* Session start panel */}
      {!sessionId && (
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-md space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800">
            <h2 className="font-semibold text-slate-800 dark:text-slate-200">Start a Chat Session</h2>
            <p className="text-sm text-slate-500">
              Select a repository to chat about. The agent will read, write, and run code in that repo.
            </p>

            {repos.length > 0 && (
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
                  Repository
                </label>
                <select
                  value={selectedRepo}
                  onChange={(e) => setSelectedRepo(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-700"
                >
                  <option value="">— select a repo —</option>
                  {repos.map((r) => (
                    <option key={r.id} value={r.localPath}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
                {repos.length > 0 ? "Or enter a custom path" : "Repo path"}
              </label>
              <input
                type="text"
                value={customPath}
                onChange={(e) => setCustomPath(e.target.value)}
                placeholder="/absolute/path/to/repo"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-700"
              />
            </div>

            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

            <button
              onClick={() => void startSession()}
              disabled={!repoPath}
              className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Start Session
            </button>
          </div>
        </div>
      )}

      {/* Chat area */}
      {sessionId && (
        <div className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center text-center text-slate-400">
                <div>
                  <p className="text-4xl mb-3">🤖</p>
                  <p className="font-medium">Agent ready</p>
                  <p className="text-sm mt-1">
                    Ask me to read files, fix bugs, write code, run tests, commit changes...
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2 justify-center">
                    {[
                      "Show me the project structure",
                      "Find all TODO comments",
                      "Run the test suite",
                      "What are the recent git commits?",
                    ].map((hint) => (
                      <button
                        key={hint}
                        onClick={() => setInput(hint)}
                        className="rounded-full border border-slate-200 px-3 py-1 text-xs hover:bg-slate-50 dark:border-slate-700"
                      >
                        {hint}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {messages.map((msg) => {
              if (msg.kind === "text") {
                if (!msg.content && !streaming) return null;
                return (
                  <div
                    key={msg.id}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl px-4 py-2.5 ${
                        msg.role === "user"
                          ? "bg-blue-600 text-white"
                          : "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100"
                      }`}
                    >
                      {msg.role === "user" ? (
                        <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                      ) : (
                        <>
                          {msg.content ? (
                            <AssistantText content={msg.content} />
                          ) : (
                            <span className="flex gap-1 items-center text-slate-400 text-xs">
                              <span className="animate-bounce [animation-delay:0ms]">●</span>
                              <span className="animate-bounce [animation-delay:150ms]">●</span>
                              <span className="animate-bounce [animation-delay:300ms]">●</span>
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                );
              }

              if (msg.kind === "tool_call") {
                return (
                  <div key={msg.id} className="ml-2">
                    <ToolCallBlock msg={msg} onToggle={() => toggleTool(msg.id)} />
                  </div>
                );
              }

              if (msg.kind === "confirm") {
                return (
                  <div key={msg.id}>
                    <ConfirmBlock msg={msg} onConfirm={(id, approved) => void handleConfirm(id, approved)} />
                  </div>
                );
              }

              return null;
            })}

            {error && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
                ⚠ {error}
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input area */}
          <div className="border-t border-slate-200 p-3 dark:border-slate-700">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything about the codebase… (Enter to send, Shift+Enter for newline)"
                rows={2}
                disabled={streaming}
                className="flex-1 resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
              <button
                onClick={() => void sendMessage()}
                disabled={!input.trim() || streaming}
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 shrink-0"
              >
                {streaming ? (
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                ) : (
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
                  </svg>
                )}
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-slate-400">
              36 tools available · reads files · edits code · runs tests · manages git · asks before destructive ops
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
