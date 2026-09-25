"use client";

import { useCallback, useRef, useState } from "react";
import { TerminalPanel } from "./TerminalPanel";

// ---------------------------------------------------------------------------
// #5 — multiple independent terminal tabs per chat session.
//
// Each tab renders its OWN <TerminalPanel>, which opens its OWN WebSocket ->
// its OWN independent PtySession/Docker container on the backend (the
// backend endpoint was never a singleton — every WS connection to
// /api/terminal/ws/{chat_session_id} already gets a fresh PtySession, so no
// backend change was needed for this). Closing one tab unmounts only that
// TerminalPanel, whose own cleanup effect closes just that WebSocket — the
// backend's existing per-connection `finally` block kills only that specific
// container, leaving every other open tab's session untouched. React's
// `key={tab.id}` is what makes each tab's underlying PtySession genuinely
// independent rather than one shared, re-rendered instance.
//
// Known, documented limitation (verified live, not assumed): a backend
// crash/restart tears the container down too, because it's a foreground
// `docker run -it` attached to a pty file descriptor the backend process
// itself owns — closing that fd (backend death) makes the docker CLI see
// EOF and exit, and `--rm` removes the container. There is no orphan/leak
// risk from this, but it also means a terminal tab cannot be reattached to
// its exact prior shell state after a backend restart — reopening a tab
// after a restart starts a brand new shell, same as opening a first one.
// True reattachment would need a fundamentally different architecture
// (e.g. a detached, backend-independent container + a separate `docker
// exec` reconnect flow) — out of scope here, not silently glossed over.
// ---------------------------------------------------------------------------

interface Tab {
  id: string;
  label: string;
}

interface TerminalTabsProps {
  chatSessionId: string;
  visible: boolean;
}

export function TerminalTabs({ chatSessionId, visible }: TerminalTabsProps) {
  const [tabs, setTabs] = useState<Tab[]>([{ id: "t-1", label: "Terminal 1" }]);
  const [activeId, setActiveId] = useState<string>("t-1");
  const nextNumberRef = useRef(2);

  const addTab = useCallback(() => {
    const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const label = `Terminal ${nextNumberRef.current++}`;
    setTabs((prev) => [...prev, { id, label }]);
    setActiveId(id);
  }, []);

  const closeTab = useCallback(
    (id: string) => {
      setTabs((prev) => {
        const idx = prev.findIndex((t) => t.id === id);
        const next = prev.filter((t) => t.id !== id);
        if (activeId === id) {
          const fallback = next[idx] ?? next[idx - 1] ?? next[0];
          setActiveId(fallback ? fallback.id : "");
        }
        return next;
      });
    },
    [activeId],
  );

  return (
    <div
      className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700"
      style={{ display: visible ? "flex" : "none" }}
    >
      <div className="flex items-center gap-1 overflow-x-auto border-b border-slate-200 bg-slate-50 px-2 py-1 dark:border-slate-700 dark:bg-slate-900" role="tablist">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`flex shrink-0 items-center gap-1.5 rounded-lg pl-3 pr-1 py-1 text-xs ${
              activeId === tab.id
                ? "bg-slate-950 text-white"
                : "text-slate-500 hover:bg-slate-200 dark:text-slate-400 dark:hover:bg-slate-800"
            }`}
          >
            <button
              onClick={() => setActiveId(tab.id)}
              role="tab"
              aria-selected={activeId === tab.id}
            >
              {tab.label}
            </button>
            <button
              onClick={() => closeTab(tab.id)}
              aria-label={`Close ${tab.label}`}
              className="rounded px-1 text-slate-400 hover:bg-black/20 hover:text-red-300"
            >
              ×
            </button>
          </div>
        ))}
        <button
          onClick={addTab}
          aria-label="New terminal"
          className="shrink-0 rounded-lg px-2 py-1 text-sm text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800"
        >
          +
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {tabs.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-sm text-slate-400">
            <button
              onClick={addTab}
              className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              + New Terminal
            </button>
          </div>
        ) : (
          tabs.map((tab) => (
            <TerminalPanel
              key={tab.id}
              chatSessionId={chatSessionId}
              visible={visible && activeId === tab.id}
            />
          ))
        )}
      </div>
    </div>
  );
}
