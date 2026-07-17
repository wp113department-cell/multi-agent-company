"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { fetchAppSettings, saveApiKey, deleteApiKey, type AppSettings } from "../../lib/api";

// ---------------------------------------------------------------------------
// API helpers for new endpoints
// ---------------------------------------------------------------------------

async function saveOpenAiKey(key: string) {
  const res = await fetch("/api/settings/openai-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: key }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Save failed");
  }
  return res.json();
}

async function deleteOpenAiKey() {
  const res = await fetch("/api/settings/openai-key", { method: "DELETE" });
  if (!res.ok) throw new Error("Delete failed");
  return res.json();
}

async function verifyKey(provider: "anthropic" | "openai", key: string) {
  const res = await fetch("/api/settings/verify-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, api_key: key }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Verify failed");
  }
  return res.json() as Promise<{ ok: boolean; provider: string; error?: string }>;
}

// ---------------------------------------------------------------------------
// Reusable key section component
// ---------------------------------------------------------------------------

type VerifyState = { status: "idle" | "pending" | "ok" | "error"; message?: string };

function ApiKeySection({
  provider,
  label,
  placeholder,
  hint,
  isSet,
  masked,
  source,
  onSave,
  onDelete,
  isSaving,
  isDeleting,
}: {
  provider: "anthropic" | "openai";
  label: string;
  placeholder: string;
  hint: string;
  isSet: boolean;
  masked: string;
  source: string;
  onSave: (key: string) => void;
  onDelete: () => void;
  isSaving: boolean;
  isDeleting: boolean;
}) {
  const [input, setInput] = useState("");
  const [verifyInput, setVerifyInput] = useState("");
  const [verify, setVerify] = useState<VerifyState>({ status: "idle" });
  const [saveSuccess, setSaveSuccess] = useState(false);

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    onSave(input.trim());
    setSaveSuccess(true);
    setInput("");
    setTimeout(() => setSaveSuccess(false), 3000);
  }

  async function handleVerify() {
    const key = verifyInput.trim() || (isSet ? "STORED_KEY_PLACEHOLDER" : "");
    if (!key || key === "STORED_KEY_PLACEHOLDER") {
      setVerify({ status: "error", message: "Paste a key to verify" });
      return;
    }
    setVerify({ status: "pending" });
    try {
      const result = await verifyKey(provider, verifyInput.trim());
      if (result.ok) {
        setVerify({ status: "ok", message: `Connected to ${label} successfully` });
      } else {
        setVerify({ status: "error", message: result.error ?? "Verification failed" });
      }
    } catch (err) {
      setVerify({ status: "error", message: err instanceof Error ? err.message : "Network error" });
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900">
      <h2 className="mb-1 text-sm font-semibold text-slate-800 dark:text-slate-200">{label}</h2>
      <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">{hint}</p>

      {/* Current status */}
      <div className="mb-4 rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-800">
        <div className="flex items-center justify-between">
          <span className="text-slate-600 dark:text-slate-300">
            Status:{" "}
            {isSet ? (
              <span className="font-medium text-green-700 dark:text-green-400">Set</span>
            ) : (
              <span className="font-medium text-amber-600 dark:text-amber-400">Not set</span>
            )}
          </span>
          <span className="text-xs capitalize text-slate-400">Source: {source}</span>
        </div>
        {isSet && (
          <p className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{masked}</p>
        )}
      </div>

      {/* Save key form */}
      <form onSubmit={handleSave} className="mb-4 space-y-2">
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400">
          Add / replace key
        </label>
        <div className="flex gap-2">
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={placeholder}
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <button
            type="submit"
            disabled={!input.trim() || isSaving}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {isSaving ? "Saving…" : "Save"}
          </button>
        </div>
        {saveSuccess && (
          <p className="text-xs text-green-600 dark:text-green-400">
            Saved — effective immediately.
          </p>
        )}
        {source === "database" && (
          <button
            type="button"
            onClick={onDelete}
            disabled={isDeleting}
            className="text-xs text-red-500 hover:underline disabled:opacity-50"
          >
            {isDeleting ? "Removing…" : "Remove stored key"}
          </button>
        )}
      </form>

      {/* Verify key section */}
      <div className="border-t border-slate-100 pt-4 dark:border-slate-700">
        <label className="mb-2 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Verify a key (paste to test — not saved)
        </label>
        <div className="flex gap-2">
          <input
            type="password"
            value={verifyInput}
            onChange={(e) => { setVerifyInput(e.target.value); setVerify({ status: "idle" }); }}
            placeholder={placeholder}
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <button
            type="button"
            onClick={handleVerify}
            disabled={verify.status === "pending" || !verifyInput.trim()}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
          >
            {verify.status === "pending" ? "Checking…" : "Verify"}
          </button>
        </div>
        {verify.status === "ok" && (
          <div className="mt-2 flex items-center gap-1.5 text-sm text-green-700 dark:text-green-400">
            <span className="text-base">✓</span>
            <span>{verify.message}</span>
          </div>
        )}
        {verify.status === "error" && (
          <div className="mt-2 flex items-start gap-1.5 text-sm text-red-600 dark:text-red-400">
            <span className="text-base leading-tight">✗</span>
            <span>{verify.message}</span>
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main settings page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery<AppSettings>({
    queryKey: ["app-settings"],
    queryFn: fetchAppSettings,
  });

  // Anthropic mutations
  const saveAnthropicMutation = useMutation({
    mutationFn: (key: string) => saveApiKey(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });
  const deleteAnthropicMutation = useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });

  // OpenAI mutations
  const saveOpenAiMutation = useMutation({
    mutationFn: (key: string) => saveOpenAiKey(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });
  const deleteOpenAiMutation = useMutation({
    mutationFn: deleteOpenAiKey,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Settings</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Runtime configuration — changes take effect immediately without restart.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : (
        <>
          <ApiKeySection
            provider="anthropic"
            label="Anthropic API Key"
            placeholder="sk-ant-..."
            hint="Powers all 68 fleet agents. Stored in your local PostgreSQL database — never leaves your machine."
            isSet={settings?.anthropicKeySet ?? false}
            masked={settings?.anthropicKeyMasked ?? ""}
            source={settings?.anthropicKeySource ?? "none"}
            onSave={(key) => saveAnthropicMutation.mutate(key)}
            onDelete={() => deleteAnthropicMutation.mutate()}
            isSaving={saveAnthropicMutation.isPending}
            isDeleting={deleteAnthropicMutation.isPending}
          />

          <ApiKeySection
            provider="openai"
            label="OpenAI API Key"
            placeholder="sk-..."
            hint="Optional. Used by agents or tools that need GPT models. Stored locally in your database."
            isSet={(settings as AppSettings & { openaiKeySet?: boolean })?.openaiKeySet ?? false}
            masked={(settings as AppSettings & { openaiKeyMasked?: string })?.openaiKeyMasked ?? ""}
            source={(settings as AppSettings & { openaiKeySource?: string })?.openaiKeySource ?? "none"}
            onSave={(key) => saveOpenAiMutation.mutate(key)}
            onDelete={() => deleteOpenAiMutation.mutate()}
            isSaving={saveOpenAiMutation.isPending}
            isDeleting={deleteOpenAiMutation.isPending}
          />

          {/* Model config (read-only) */}
          {settings && (
            <section className="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900">
              <h2 className="mb-1 text-sm font-semibold text-slate-800 dark:text-slate-200">
                Model Configuration
              </h2>
              <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
                Change via env vars in your{" "}
                <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">.env</code> file.
              </p>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-500 dark:text-slate-400">Backend</dt>
                  <dd className="font-medium text-slate-800 dark:text-slate-200">
                    {settings.usingGroq ? "Groq" : "Anthropic"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500 dark:text-slate-400">Planner model</dt>
                  <dd className="font-mono text-xs text-slate-700 dark:text-slate-300">{settings.modelPlanner}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500 dark:text-slate-400">Coder model</dt>
                  <dd className="font-mono text-xs text-slate-700 dark:text-slate-300">{settings.modelCoder}</dd>
                </div>
              </dl>
            </section>
          )}
        </>
      )}
    </div>
  );
}
