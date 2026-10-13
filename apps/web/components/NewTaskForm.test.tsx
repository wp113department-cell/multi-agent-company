/**
 * Sol A33 (2026-10-13): a failed image upload never leads to a second task.
 * The task is created once; pressing the button again only retries the
 * upload, and every attempt of one submission carries the same
 * Idempotency-Key.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

const createTask = vi.fn();
const uploadTaskImages = vi.fn();

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  createTask: (...a: unknown[]) => createTask(...a),
  uploadTaskImages: (...a: unknown[]) => uploadTaskImages(...a),
  fetchAppSettings: async () => ({}),
}));

import { NewTaskForm } from "./NewTaskForm";
import type { ProjectDetail } from "../lib/api";

const project = {
  id: 7,
  name: "Demo",
  goals: [],
  epics: [],
  history: [],
} as unknown as ProjectDetail;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NewTaskForm project={project} />
    </QueryClientProvider>,
  );
}

describe("NewTaskForm with images (Sol A33)", () => {
  it("retries only the upload after a failed upload — one task", async () => {
    createTask.mockResolvedValue({ id: 5, title: "Add a shop page" });
    uploadTaskImages
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValueOnce({ ok: true });

    const { container } = renderForm();
    fireEvent.change(screen.getByLabelText(/describe|what should/i), {
      target: { value: "Add a shop page" },
    });
    fireEvent.click(screen.getByRole("button", { name: /attach files/i }));
    const fileInput = container.querySelector('input[type="file"][accept*="image"]') as HTMLInputElement;
    const image = new File(["x"], "design.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [image] } });

    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText(/was created, but its images did not upload/);
    const retry = await screen.findByRole("button", { name: "Retry image upload" });

    fireEvent.click(retry);
    await waitFor(() => expect(uploadTaskImages).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Create task" })).toBeTruthy());

    expect(createTask).toHaveBeenCalledTimes(1);
    expect(uploadTaskImages.mock.calls.every((c) => c[0] === 5)).toBe(true);
    expect((createTask.mock.calls[0]?.[0] as { idempotencyKey?: string }).idempotencyKey).toMatch(/[0-9a-f-]{36}/);
  });
});
