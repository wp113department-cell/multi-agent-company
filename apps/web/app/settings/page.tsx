"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { fetchAppSettings, saveApiKey, deleteApiKey, type AppSettings } from "../../lib/api";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [saveSuccess, setSaveSuccess] = useState(false);

  const { data: settings, isLoading } = useQuery<AppSettings>({
    queryKey: ["app-settings"],
    queryFn: fetchAppSettings,
  });

  const saveMutation = useMutation({
    mutationFn: () => saveApiKey(apiKeyInput),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["app-settings"] });
      setApiKeyInput("");
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["app-settings"] });
    },
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (apiKeyInput.trim()) saveMutation.mutate();
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          Runtime configuration — changes take effect immediately without restart.
        </p>
      </div>

      {/* Anthropic API Key */}
      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-1 text-sm font-semibold text-slate-800">Anthropic API Key</h2>
        <p className="mb-4 text-xs text-slate-500">
          Enter your key here to avoid editing the <code className="rounded bg-slate-100 px-1">.env</code> file.
          The key is stored locally in your PostgreSQL database — it never leaves your machine.
        </p>

        {isLoading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : (
          <div className="mb-4 rounded-md bg-slate-50 p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">
                Status:{" "}
                {settings?.anthropicKeySet ? (
                  <span className="font-medium text-green-700">Set</span>
                ) : (
                  <span className="font-medium text-red-600">Not set</span>
                )}
              </span>
              <span className="text-xs text-slate-400 capitalize">
                Source: {settings?.anthropicKeySource ?? "unknown"}
              </span>
            </div>
            {settings?.anthropicKeySet && (
              <p className="mt-1 font-mono text-xs text-slate-500">{settings.anthropicKeyMasked}</p>
            )}
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-3">
          <input
            type="password"
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.target.value)}
            placeholder="sk-ant-..."
            className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!apiKeyInput.trim() || saveMutation.isPending}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving…" : "Save Key"}
            </button>
            {settings?.anthropicKeySource === "database" && (
              <button
                type="button"
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
                className="rounded-md border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Removing…" : "Remove DB Key"}
              </button>
            )}
          </div>
          {saveSuccess && (
            <p className="text-sm text-green-600">Key saved — agents will use it immediately.</p>
          )}
          {saveMutation.isError && (
            <p className="text-sm text-red-600">
              {saveMutation.error instanceof Error ? saveMutation.error.message : "Save failed"}
            </p>
          )}
        </form>
      </section>

      {/* Model Config (read-only) */}
      {settings && (
        <section className="rounded-lg border border-slate-200 bg-white p-6">
          <h2 className="mb-1 text-sm font-semibold text-slate-800">Model Configuration</h2>
          <p className="mb-4 text-xs text-slate-500">
            Change these via environment variables in your <code className="rounded bg-slate-100 px-1">.env</code> file.
          </p>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Backend (Groq active)</dt>
              <dd className="font-medium text-slate-800">{settings.usingGroq ? "Groq" : "Anthropic"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Planner model</dt>
              <dd className="font-mono text-xs text-slate-700">{settings.modelPlanner}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Coder model</dt>
              <dd className="font-mono text-xs text-slate-700">{settings.modelCoder}</dd>
            </div>
          </dl>
        </section>
      )}
    </div>
  );
}
