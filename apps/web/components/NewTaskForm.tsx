"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { createTask, extractPdfs, listRepos, type PdfFileResult } from "../lib/api";

const MAX_PDFS = 5;
// Allow up to 500k chars (~125k tokens) — fits both Anthropic and OpenAI limits
const MAX_DESC_CHARS = 500_000;

export function NewTaskForm() {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"low" | "medium" | "high">("medium");
  const [repoId, setRepoId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);

  // PDF state
  const [pdfs, setPdfs] = useState<File[]>([]);
  const [pdfResults, setPdfResults] = useState<PdfFileResult[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [pdfError, setPdfError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();

  const { data: repoData } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    staleTime: 30000,
  });

  const readyRepos = repoData?.repos.filter((r) => r.status === "ready") ?? [];

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
    mutationFn: () =>
      createTask({ title, description: buildFinalDescription(), repoId }),
    onSuccess: () => {
      setTitle("");
      setDescription("");
      setRepoId(null);
      setPdfs([]);
      setPdfResults([]);
      setPdfError("");
      setExpanded(false);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

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

  return (
    <form
      className="mb-6 space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim() && !overLimit) mutation.mutate();
      }}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Submit a development task
        </h2>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>

      {/* Title */}
      <input
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
        placeholder="Title — e.g. Add a new endpoint that shows worker queue status"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />

      {/* Description — large textarea */}
      <div>
        <textarea
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          placeholder="Describe the task in as much detail as you like. Paste a full spec, code snippets, error messages, or any context the agents need. No fixed limit — the more detail, the better the output."
          rows={expanded ? 16 : 4}
          value={description}
          onChange={(e) => {
            setDescription(e.target.value);
            if (!expanded && e.target.value.length > 100) setExpanded(true);
          }}
        />
        <div className="mt-1 flex items-center justify-between">
          <span className="text-xs text-slate-400">
            {description.length.toLocaleString()} chars
            {pdfResults.length > 0 && (
              <> + {pdfResults.reduce((s, f) => s + f.chars, 0).toLocaleString()} from PDFs</>
            )}
          </span>
          {overLimit ? (
            <span className="text-xs font-medium text-red-600">
              Total exceeds {(MAX_DESC_CHARS / 1000).toFixed(0)}k chars limit — reduce content
            </span>
          ) : finalChars > 0 ? (
            <span className="text-xs text-slate-400">
              Total: {finalChars.toLocaleString()} / {(MAX_DESC_CHARS / 1000).toFixed(0)}k chars
            </span>
          ) : null}
        </div>
      </div>

      {/* PDF attachments */}
      <div>
        <div className="mb-1.5 flex items-center gap-2">
          <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Attach PDFs ({pdfs.length}/{MAX_PDFS})
          </span>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={pdfs.length >= MAX_PDFS}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
          >
            + Add PDF
          </button>
          {extracting && <span className="text-xs text-indigo-500">Extracting text…</span>}
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
              <li
                key={i}
                className="flex items-center gap-2 rounded bg-slate-50 px-3 py-1.5 dark:bg-slate-800"
              >
                <span className="text-base">📄</span>
                <span className="flex-1 truncate text-xs text-slate-700 dark:text-slate-300">
                  {f.name}
                </span>
                {pdfResults[i] && (
                  <span className="text-xs text-slate-400">
                    {pdfResults[i].chars.toLocaleString()} chars
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => removePdf(i)}
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

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
          value={priority}
          onChange={(e) => setPriority(e.target.value as typeof priority)}
        >
          <option value="low">Low priority</option>
          <option value="medium">Medium priority</option>
          <option value="high">High priority</option>
        </select>

        {readyRepos.length > 0 && (
          <select
            className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
            value={repoId ?? ""}
            onChange={(e) => setRepoId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Default repo</option>
            {readyRepos.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} {r.isActive ? "(active)" : ""}
              </option>
            ))}
          </select>
        )}

        <button
          type="submit"
          disabled={mutation.isPending || overLimit || extracting || !title.trim()}
          className="whitespace-nowrap rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {mutation.isPending ? "Submitting…" : "Submit task"}
        </button>
      </div>

      {mutation.isError && (
        <p className="text-sm text-red-600">
          {mutation.error instanceof Error ? mutation.error.message : "Submit failed"}
        </p>
      )}
    </form>
  );
}
