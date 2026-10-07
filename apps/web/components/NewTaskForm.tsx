"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  addProjectEpic,
  addProjectGoal,
  createTask,
  extractPdfs,
  uploadTaskImages,
  type PdfFileResult,
  type ProjectDetail,
} from "../lib/api";

const MAX_PDFS = 5;
const MAX_IMAGES = 20;
const IMAGE_ACCEPT = "image/png,image/jpeg,image/gif,image/webp";
// Allow up to 500k chars (~125k tokens) — fits both Anthropic and OpenAI limits
const MAX_DESC_CHARS = 500_000;

/** A short title from the description: its first line, trimmed. */
function titleFrom(description: string): string {
  const first = description.trim().split(/\r?\n/)[0] ?? "";
  return first.length > 120 ? `${first.slice(0, 117)}…` : first;
}

const MODES = [
  {
    id: "economy" as const,
    title: "Economy",
    badge: "Default",
    text: "Uses the fewest agents and smaller models. Best for most tasks and keeps cost low.",
  },
  {
    id: "max" as const,
    title: "Max",
    badge: "Full team",
    text: "Runs the whole pipeline: planning, architecture, all checks and reviews. Slower and costs more.",
  },
];

/** Optional goal/epic of the selected project: pick one or create a new one. */
function LabelPicker({
  kind,
  options,
  value,
  onChange,
  onCreate,
}: {
  kind: "Goal" | "Epic";
  options: { id: string; title: string }[];
  value: string;
  onChange: (id: string) => void;
  onCreate: (title: string) => Promise<string>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = `task-${kind.toLowerCase()}`;
  const help =
    kind === "Goal"
      ? "A business outcome this task helps with, e.g. “Faster customer replies”."
      : "A bigger piece of work this task belongs to, e.g. “Customer chat improvements”.";

  async function create() {
    if (!title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const newId = await onCreate(title.trim());
      onChange(newId);
      setTitle("");
      setAdding(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not create the ${kind.toLowerCase()}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label htmlFor={id} className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {kind} <span className="font-normal text-slate-400">(optional)</span>
        </label>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="text-xs font-semibold text-orange-600 hover:text-orange-700"
          >
            ＋ New {kind.toLowerCase()}
          </button>
        )}
      </div>
      {adding ? (
        <div className="flex gap-2">
          <input
            aria-label={`New ${kind.toLowerCase()} name`}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void create();
              }
            }}
            placeholder={kind === "Goal" ? "Improve customer response automation" : "Customer chat improvements"}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <button
            type="button"
            onClick={() => void create()}
            disabled={busy || !title.trim()}
            className="rounded-lg bg-orange-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? "…" : "Add"}
          </button>
          <button
            type="button"
            onClick={() => setAdding(false)}
            className="rounded-lg px-2 py-2 text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Cancel
          </button>
        </div>
      ) : (
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
        >
          <option value="">None</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.title}
            </option>
          ))}
        </select>
      )}
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{help}</p>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

export function NewTaskForm({ project }: { project: ProjectDetail | null }) {
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"medium" | "high">("medium");
  const [mode, setMode] = useState<"economy" | "max">("economy");
  const [goalId, setGoalId] = useState("");
  const [epicId, setEpicId] = useState("");
  const [showAttach, setShowAttach] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  // PDF state
  const [pdfs, setPdfs] = useState<File[]>([]);
  const [pdfResults, setPdfResults] = useState<PdfFileResult[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [pdfError, setPdfError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Image state (Day 16 — Image Input Pipeline)
  const [images, setImages] = useState<File[]>([]);
  const [imageError, setImageError] = useState("");
  const imageInputRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();

  // a different project: its goals/epics differ
  useEffect(() => {
    setGoalId("");
    setEpicId("");
  }, [project?.id]);

  function buildFinalDescription(): string {
    let text = description;
    if (pdfResults.length > 0) {
      const pdfSection = pdfResults
        .map((f) => `\n\n--- Attachment: ${f.filename} ---\n${f.text}`)
        .join("\n");
      text = text + pdfSection;
    }
    return text;
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const task = await createTask({
        title: titleFrom(description),
        description: buildFinalDescription(),
        projectId: project?.id ?? null,
        goalId: goalId || null,
        epicId: epicId || null,
        priority,
        executionMode: mode,
      });
      if (images.length > 0) {
        // Images are stored against a real task_id (unlike PDFs, which just
        // extract text client-side) — upload happens after task creation.
        await uploadTaskImages(task.id, images);
      }
      return task;
    },
    onSuccess: (task) => {
      setCreated(task.title);
      setDescription("");
      setPdfs([]);
      setPdfResults([]);
      setPdfError("");
      setImages([]);
      setImageError("");
      setShowAttach(false);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["project", project?.id] });
    },
  });

  function handleImageChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    const newFiles = [...images, ...files].slice(0, MAX_IMAGES);
    if (files.length + images.length > MAX_IMAGES) {
      setImageError(`Maximum ${MAX_IMAGES} images allowed.`);
    } else {
      setImageError("");
    }
    setImages(newFiles);
    if (imageInputRef.current) imageInputRef.current.value = "";
  }

  function removeImage(idx: number) {
    setImages(images.filter((_, i) => i !== idx));
  }

  const imagePreviews = useMemo(() => images.map((f) => URL.createObjectURL(f)), [images]);
  useEffect(() => {
    return () => {
      imagePreviews.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [imagePreviews]);

  async function handlePdfChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    const newFiles = [...pdfs, ...files].slice(0, MAX_PDFS);
    if (files.length + pdfs.length > MAX_PDFS) {
      setPdfError(`Maximum ${MAX_PDFS} PDFs allowed.`);
    }
    setPdfs(newFiles);
    setPdfError("");
    setExtracting(true);
    try {
      const results = await extractPdfs(newFiles);
      setPdfResults(results);
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : "PDF extraction failed");
    } finally {
      setExtracting(false);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removePdf(idx: number) {
    setPdfs(pdfs.filter((_, i) => i !== idx));
    setPdfResults(pdfResults.filter((_, i) => i !== idx));
  }

  const finalChars = buildFinalDescription().length;
  const overLimit = finalChars > MAX_DESC_CHARS;
  const canSubmit = !!project && description.trim().length > 0 && !overLimit && !extracting;

  return (
    <form
      aria-label="Create a task"
      className="space-y-5 rounded-2xl border border-orange-100 bg-white p-5 shadow-soft sm:p-6 dark:border-slate-700 dark:bg-slate-900"
      onSubmit={(e) => {
        e.preventDefault();
        setCreated(null);
        if (canSubmit) mutation.mutate();
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">New task</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {project ? (
              <>
                For <span className="font-semibold text-orange-700 dark:text-orange-300">{project.name}</span>. Describe what
                you need in plain words.
              </>
            ) : (
              "Choose a project first."
            )}
          </p>
        </div>
      </div>

      <div>
        <label htmlFor="task-description" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
          What should be done?
        </label>
        <textarea
          id="task-description"
          className={`h-28 w-full resize-y rounded-lg border px-3 py-2 text-sm dark:bg-slate-800 dark:text-slate-100 ${
            overLimit ? "border-red-400" : "border-slate-300 dark:border-slate-600"
          }`}
          placeholder="e.g. Add a function subtract(a: int, b: int) -> int returning a - b to demo_module.py"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={!project}
        />
        <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
          <button
            type="button"
            onClick={() => setShowAttach((s) => !s)}
            className="font-medium text-orange-600 hover:text-orange-700"
          >
            📎 {showAttach ? "Hide attachments" : "Attach files (PDFs, images)"}
            {pdfs.length + images.length > 0 ? ` · ${pdfs.length + images.length} attached` : ""}
          </button>
          <span className={overLimit ? "font-medium text-red-600" : ""}>
            {overLimit ? `Too long: ${finalChars.toLocaleString()} characters` : ""}
          </span>
        </div>
      </div>

      {showAttach && (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3 dark:border-slate-700 dark:bg-slate-800/40">
          {/* PDF attachments */}
          <div>
            <div className="mb-1.5 flex items-center gap-2">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                PDFs ({pdfs.length}/{MAX_PDFS})
              </span>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={pdfs.length >= MAX_PDFS}
                className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
              >
                + Add PDF
              </button>
              {extracting && <span className="text-xs text-orange-600">Reading the PDF…</span>}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              onChange={handlePdfChange}
              className="hidden"
            />
            {pdfs.length > 0 && (
              <ul className="space-y-1">
                {pdfs.map((f, i) => (
                  <li key={i} className="flex items-center gap-2 rounded bg-white px-3 py-1.5 dark:bg-slate-800">
                    <span className="text-base">📄</span>
                    <span className="flex-1 truncate text-xs text-slate-700 dark:text-slate-300">{f.name}</span>
                    {pdfResults[i] && (
                      <span className="text-xs text-slate-400">{pdfResults[i].chars.toLocaleString()} chars</span>
                    )}
                    <button
                      type="button"
                      onClick={() => removePdf(i)}
                      aria-label={`Remove ${f.name}`}
                      className="ml-1 text-xs text-red-400 hover:text-red-600"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {pdfError && <p className="mt-1 text-xs text-red-600">{pdfError}</p>}
          </div>

          {/* Reference images (Day 16 — Image Input Pipeline) */}
          <div>
            <div className="mb-1.5 flex items-center gap-2">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Images, e.g. a design or a screenshot ({images.length}/{MAX_IMAGES})
              </span>
              <button
                type="button"
                onClick={() => imageInputRef.current?.click()}
                disabled={images.length >= MAX_IMAGES}
                className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
              >
                + Add image
              </button>
            </div>
            <input
              ref={imageInputRef}
              type="file"
              accept={IMAGE_ACCEPT}
              multiple
              onChange={handleImageChange}
              className="hidden"
            />
            {images.length > 0 && (
              <ul className="flex flex-wrap gap-2">
                {images.map((f, i) => (
                  <li key={i} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={imagePreviews[i]}
                      alt={f.name}
                      className="h-16 w-16 rounded border border-slate-300 object-cover dark:border-slate-600"
                    />
                    <button
                      type="button"
                      onClick={() => removeImage(i)}
                      className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] text-white hover:bg-red-600"
                      aria-label={`Remove ${f.name}`}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {imageError && <p className="mt-1 text-xs text-red-600">{imageError}</p>}
          </div>
        </div>
      )}

      {project && (
        <div className="grid gap-4 md:grid-cols-2">
          <LabelPicker
            kind="Goal"
            options={project.goals}
            value={goalId}
            onChange={setGoalId}
            onCreate={async (t) => {
              const g = await addProjectGoal(project.id, t);
              await queryClient.invalidateQueries({ queryKey: ["project", project.id] });
              return g.id;
            }}
          />
          <LabelPicker
            kind="Epic"
            options={project.epics}
            value={epicId}
            onChange={setEpicId}
            onCreate={async (t) => {
              const e = await addProjectEpic(project.id, t);
              await queryClient.invalidateQueries({ queryKey: ["project", project.id] });
              return e.id;
            }}
          />
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[auto_1fr]">
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-slate-700 dark:text-slate-300">Priority</legend>
          <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800">
            {(["medium", "high"] as const).map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={priority === p}
                onClick={() => setPriority(p)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium ${
                  priority === p
                    ? p === "high"
                      ? "bg-red-600 text-white shadow-sm"
                      : "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white"
                    : "text-slate-500"
                }`}
              >
                {p === "high" ? "High" : "Medium"}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-slate-700 dark:text-slate-300">How should the team work?</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                aria-pressed={mode === m.id}
                onClick={() => setMode(m.id)}
                className={`rounded-xl border p-3 text-left transition ${
                  mode === m.id
                    ? "border-orange-400 bg-orange-50 shadow-[0_0_0_1px_rgba(249,115,22,0.4)] dark:bg-orange-950/30"
                    : "border-slate-200 bg-white hover:border-orange-200 dark:border-slate-700 dark:bg-slate-900"
                }`}
              >
                <span className="flex items-center justify-between">
                  <span className="font-semibold text-slate-900 dark:text-white">{m.title}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {m.badge}
                  </span>
                </span>
                <span className="mt-1 block text-xs leading-snug text-slate-600 dark:text-slate-400">{m.text}</span>
              </button>
            ))}
          </div>
        </fieldset>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-h-[1.25rem] text-sm">
          {mutation.isError && (
            <p role="alert" className="text-red-600">
              {mutation.error instanceof Error ? mutation.error.message : "Could not create the task"}
            </p>
          )}
          {created && !mutation.isError && (
            <p className="text-green-700 dark:text-green-400">✓ Task created. Press “Start” on it below when you are ready.</p>
          )}
        </div>
        <button
          type="submit"
          disabled={!canSubmit || mutation.isPending}
          className="rounded-lg bg-orange-600 px-6 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {mutation.isPending ? "Creating…" : "Create task"}
        </button>
      </div>
    </form>
  );
}
