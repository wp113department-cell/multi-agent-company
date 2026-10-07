import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as auth from "../lib/auth";
import { ApprovalsPanel } from "./ApprovalsPanel";

const question = {
  id: 1,
  threadId: "question-1",
  taskId: 42,
  agentName: "planner",
  action: "clarification",
  details: {
    question: "Which sizes should the product filter show?",
    options: [{ label: "Shop sizes (S, M, L)" }, { label: "Supplier sizes (EU 36-46)" }],
  },
  status: "pending",
  createdAt: "2026-10-07T07:00:00Z",
  decidedAt: null,
  decidedBy: null,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.spyOn(auth, "authHeaders").mockReturnValue({});
  vi.spyOn(auth, "isApprover").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ApprovalsPanel question decisions", () => {
  it("requires a nonblank answer, submits its trimmed text, and prevents another decision while sending", async () => {
    let pending = true;
    let finish!: (response: Response) => void;
    const decision = new Promise<Response>((resolve) => { finish = resolve; });
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const response = await decision;
        pending = false;
        return response;
      }
      return json({ approvals: pending ? [question] : [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalsPanel />);

    const answer = await screen.findByRole("textbox", { name: "Your answer" });
    const send = screen.getByRole("button", { name: "Send answer" });
    expect(send).toBeDisabled();
    fireEvent.change(answer, { target: { value: "   " } });
    expect(send).toBeDisabled();
    fireEvent.change(answer, { target: { value: "  Use shop sizes for all products.  " } });
    fireEvent.click(send);

    expect(fetchMock).toHaveBeenCalledWith("/api/approvals/question-1/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: "Use shop sizes for all products." }),
    });
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(answer).toBeDisabled();

    await act(async () => { finish(json({ approved: true })); });
    expect(await screen.findByText("Nothing waiting for your approval right now.")).toBeInTheDocument();
  });

  it("lets a suggested option fill an editable answer without submitting until the user confirms", async () => {
    let pending = true;
    const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        pending = false;
        return json({ approved: true });
      }
      return json({ approvals: pending ? [question] : [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Shop sizes (S, M, L)" }));
    const answer = screen.getByRole("textbox", { name: "Your answer" });
    expect(answer).toHaveValue("Shop sizes (S, M, L)");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.change(answer, { target: { value: "Shop sizes (S, M, L), plus a size guide." } });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/approvals/question-1/approve",
      expect.objectContaining({ body: JSON.stringify({ answer: "Shop sizes (S, M, L), plus a size guide." }) }),
    ));
    await screen.findByText("Nothing waiting for your approval right now.");
  });

  it("keeps the answer after a failed request and lets the user retry it", async () => {
    let pending = true;
    let attempts = 0;
    const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        attempts += 1;
        if (attempts === 1) return json({ detail: "Connection interrupted. Please try again." }, 503);
        pending = false;
        return json({ approved: true });
      }
      return json({ approvals: pending ? [question] : [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalsPanel />);

    const answer = await screen.findByRole("textbox", { name: "Your answer" });
    fireEvent.change(answer, { target: { value: "Use supplier sizes." } });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection interrupted. Please try again.");
    expect(answer).toHaveValue("Use supplier sizes.");
    expect(screen.getByRole("button", { name: "Send answer" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));

    await screen.findByText("Nothing waiting for your approval right now.");
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts.map(([, init]) => init?.body)).toEqual([
      JSON.stringify({ answer: "Use supplier sizes." }),
      JSON.stringify({ answer: "Use supplier sizes." }),
    ]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    ["clarification", "Reject", "reject"],
    ["plan_review", "Approve", "approve"],
    ["git_push", "Approve", "approve"],
  ])("keeps %s %s as a decision without an answer body", async (action, button, route) => {
    let pending = true;
    const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        pending = false;
        return json({ ok: true });
      }
      return json({ approvals: pending ? [{ ...question, action }] : [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ApprovalsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: button }));
    await screen.findByText("Nothing waiting for your approval right now.");
    expect(fetchMock).toHaveBeenCalledWith(`/api/approvals/question-1/${route}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  });

  it("shows the question to viewers without answer or decision controls", async () => {
    vi.mocked(auth.isApprover).mockReturnValue(false);
    vi.stubGlobal("fetch", vi.fn(async () => json({ approvals: [question] })));
    render(<ApprovalsPanel />);

    expect(await screen.findByText(question.details.question)).toBeInTheDocument();
    expect(screen.getByText("Approver role required to decide on this request.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
