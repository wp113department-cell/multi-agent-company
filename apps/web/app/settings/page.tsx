"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  deleteCustomSecret,
  fetchAppSettings,
  fetchCustomSecrets,
  saveApiKey,
  saveCustomSecret,
  saveGithubToken,
  type AppSettings,
} from "../../lib/api";

// ---------------------------------------------------------------------------
// API helpers
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

async function verifyKey(provider: "anthropic" | "openai", key: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch("/api/settings/verify-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, api_key: key }),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(b.detail ?? "Verify failed");
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Reusable key card: 1 input + 1 button (Verify → Save)
// ---------------------------------------------------------------------------

type Phase = "idle" | "verifying" | "verified" | "saving" | "saved";

function ApiKeyCard({
  provider,
  label,
  hint,
  placeholder,
  isSet,
  masked,
  onSave,
  isSaving,
}: {
  provider: "anthropic" | "openai" | "github";
  label: string;
  hint: string;
  placeholder: string;
  isSet: boolean;
  masked: string;
  onSave: (key: string) => Promise<void>;
  isSaving: boolean;
}) {
  // GitHub tokens have no server-side verify-key support (only Anthropic/
  // OpenAI do) — that provider skips straight from input to save.
  const skipVerify = provider === "github";

  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<Phase>(skipVerify ? "verified" : "idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleAction() {
    const key = input.trim();
    if (!key) return;

    if (skipVerify) {
      setPhase("saving");
      try {
        await onSave(key);
        setPhase("saved");
        setInput("");
        setTimeout(() => setPhase("verified"), 3000);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : "Save failed");
        setPhase("verified");
      }
      return;
    }

    if (provider !== "anthropic" && provider !== "openai") return;

    if (phase === "idle" || phase === "saved") {
      setErrorMsg("");
      setPhase("verifying");
      try {
        const result = await verifyKey(provider, key);
        if (result.ok) {
          setPhase("verified");
        } else {
          setErrorMsg(result.error ?? "Key verification failed — check the key and try again.");
          setPhase("idle");
        }
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : "Network error");
        setPhase("idle");
      }
    } else if (phase === "verified") {
      setPhase("saving");
      try {
        await onSave(key);
        setPhase("saved");
        setInput("");
        setTimeout(() => setPhase("idle"), 3000);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : "Save failed");
        setPhase("verified");
      }
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setInput(e.target.value);
    if (!skipVerify && (phase === "verified" || phase === "saved")) setPhase("idle");
    setErrorMsg("");
  }

  const buttonLabel =
    phase === "verifying" ? "Verifying…"
    : phase === "verified" ? "Save"
    : phase === "saving" ? "Saving…"
    : phase === "saved" ? "Saved ✓"
    : "Verify";

  const buttonDisabled =
    !input.trim() || phase === "verifying" || phase === "saving" || phase === "saved" || isSaving;

  const buttonClass =
    phase === "verified"
      ? "rounded-lg bg-green-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 shrink-0"
      : phase === "saved"
      ? "rounded-lg bg-green-600 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-75 shrink-0"
      : "rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 shrink-0";

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{label}</h2>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      </div>

      {/* Current status */}
      <div className="rounded-lg bg-slate-50 px-4 py-3 dark:bg-slate-800">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-600 dark:text-slate-300">
            Status:{" "}
            {isSet ? (
              <span className="font-semibold text-green-700 dark:text-green-400">Set</span>
            ) : (
              <span className="font-semibold text-amber-600 dark:text-amber-400">Not set</span>
            )}
          </span>
          {isSet && masked && (
            <span className="font-mono text-xs text-slate-400 dark:text-slate-500">{masked}</span>
          )}
        </div>
      </div>

      {/* Input + button */}
      <div className="space-y-2">
        <div className="flex gap-2">
          <input
            type="password"
            value={input}
            onChange={handleChange}
            placeholder={placeholder}
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <button onClick={handleAction} disabled={buttonDisabled} className={buttonClass}>
            {buttonLabel}
          </button>
        </div>

        {!skipVerify && phase === "verified" && (
          <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
            <span>✓</span>
            <span>Key verified — click Save to store it.</span>
          </div>
        )}
        {phase === "saved" && (
          <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
            <span>✓</span>
            <span>Key saved and active.</span>
          </div>
        )}
        {errorMsg && (
          <div className="flex items-start gap-2 text-sm text-red-600 dark:text-red-400">
            <span>✗</span>
            <span>{errorMsg}</span>
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Custom secrets (Day 17 — Credential Vault). Arbitrary named secrets
// injected into the coding agents' bash tool env — never database/deploy
// credentials (see docs/DAY17_PLAN.md). List + add form + delete, adapted
// from open-hands's secrets-settings screen to this project's simpler
// backend (create/list/delete only — no description field, no editing an
// existing secret's value, matching what POST/GET/DELETE
// /api/settings/custom-secrets actually supports).
// ---------------------------------------------------------------------------

function CustomSecretsSection() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [formError, setFormError] = useState("");

  const { data: names, isLoading } = useQuery({
    queryKey: ["custom-secrets"],
    queryFn: fetchCustomSecrets,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["custom-secrets"] });

  const createMutation = useMutation({
    mutationFn: () => saveCustomSecret(name.trim(), value.trim()),
    onSuccess: () => {
      setName("");
      setValue("");
      setFormError("");
      invalidate();
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : "Save failed"),
  });

  const deleteMutation = useMutation({
    mutationFn: (secretName: string) => deleteCustomSecret(secretName),
    onSuccess: invalidate,
  });

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim() || !value.trim()) return;
    createMutation.mutate();
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Custom Secrets</h2>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Named secrets (e.g. a third-party API key) injected into the coding agents&apos; shell
          environment. Never database credentials or deploy secrets — those are never handed to
          agents.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : names && names.length > 0 ? (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100 dark:divide-slate-800 dark:border-slate-800">
          {names.map((secretName) => (
            <li
              key={secretName}
              className="flex items-center justify-between gap-3 px-4 py-2.5"
            >
              <span className="font-mono text-sm text-slate-700 dark:text-slate-300">{secretName}</span>
              <button
                onClick={() => deleteMutation.mutate(secretName)}
                disabled={deleteMutation.isPending}
                className="text-xs font-medium text-red-500 hover:text-red-700 disabled:opacity-50 dark:text-red-400"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          No custom secrets set.
        </p>
      )}

      <form onSubmit={handleSubmit} className="space-y-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <div className="flex gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value.toUpperCase())}
            placeholder="NPM_TOKEN"
            className="w-1/3 rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Secret value"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <button
            type="submit"
            disabled={!name.trim() || !value.trim() || createMutation.isPending}
            className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {createMutation.isPending ? "Adding…" : "Add"}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          Name must be a valid env var identifier (letters, digits, underscore).
        </p>
        {formError && (
          <div className="flex items-start gap-2 text-sm text-red-600 dark:text-red-400">
            <span>✗</span>
            <span>{formError}</span>
          </div>
        )}
      </form>
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

  const saveAnthropicMutation = useMutation({
    mutationFn: (key: string) => saveApiKey(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });

  const saveOpenAiMutation = useMutation({
    mutationFn: (key: string) => saveOpenAiKey(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });

  const saveGithubMutation = useMutation({
    mutationFn: (token: string) => saveGithubToken(token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-settings"] }),
  });

  return (
    <div className="mx-auto max-w-lg space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Settings</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Runtime configuration — changes take effect immediately.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : (
        <>
          <ApiKeyCard
            provider="anthropic"
            label="Anthropic API Key"
            hint="Powers all 68 fleet agents. Stored in your local database — never leaves your machine."
            placeholder="sk-ant-..."
            isSet={settings?.anthropicKeySet ?? false}
            masked={settings?.anthropicKeyMasked ?? ""}
            onSave={(key) => saveAnthropicMutation.mutateAsync(key).then(() => {})}
            isSaving={saveAnthropicMutation.isPending}
          />

          <ApiKeyCard
            provider="openai"
            label="OpenAI API Key"
            hint="Required for GPT-based tools and embeddings used by some agents. Stored locally."
            placeholder="sk-..."
            isSet={settings?.openaiKeySet ?? false}
            masked={settings?.openaiKeyMasked ?? ""}
            onSave={(key) => saveOpenAiMutation.mutateAsync(key)}
            isSaving={saveOpenAiMutation.isPending}
          />

          <ApiKeyCard
            provider="github"
            label="GitHub Token"
            hint="Personal access token used to create pull requests once agents finish a task. Stored locally."
            placeholder="ghp_..."
            isSet={settings?.githubTokenSet ?? false}
            masked={settings?.githubTokenMasked ?? ""}
            onSave={(key) => saveGithubMutation.mutateAsync(key).then(() => {})}
            isSaving={saveGithubMutation.isPending}
          />

          <CustomSecretsSection />

          {/* Model config (read-only) */}
          {settings && (
            <section className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-900">
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
