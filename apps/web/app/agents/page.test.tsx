import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentsPage from "./page";
import * as api from "@/lib/api";

const CATALOG = {
  total: 3,
  categories: [
    {
      name: "Developers",
      description: "Write and change the code.",
      count: 2,
      agents: [
        { name: "backend_dev", displayName: "Backend Dev", purpose: "Writes server code.", tools: ["read_file", "write_file"], capabilities: ["backend"], available: true, state: "sleep", risk: "medium" },
        { name: "frontend_dev", displayName: "Frontend Dev", purpose: "Builds the UI.", tools: ["read_file"], capabilities: [], available: true, state: "sleep", risk: "medium" },
      ],
    },
    {
      name: "Testing",
      description: "Prove the code works.",
      count: 1,
      agents: [{ name: "qa", displayName: "QA", purpose: "Runs the tests.", tools: ["run_tests"], capabilities: [], available: false, state: "disabled", risk: "low" }],
    },
  ],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AgentsPage />
    </QueryClientProvider>,
  );
}

describe("AgentsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "fetchTeamCatalog").mockResolvedValue(CATALOG);
    vi.spyOn(api, "fetchCustomAgentTools").mockResolvedValue([
      { name: "read_file", description: "Read a file" },
      { name: "list_files", description: "List files" },
      { name: "search_code", description: "Search code" },
    ]);
  });

  it("shows every category with its agent count", async () => {
    vi.spyOn(api, "listCustomAgents").mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Developers")).toBeInTheDocument());
    expect(screen.getByText("Testing")).toBeInTheDocument();
    expect(screen.getByText(/3 built-in specialists/)).toBeInTheDocument();
  });

  it("opens a category to show its agents and their availability", async () => {
    vi.spyOn(api, "listCustomAgents").mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Testing")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Testing"));
    expect(screen.getByText("QA")).toBeInTheDocument();
    expect(screen.getByText("disabled")).toBeInTheDocument();
  });

  it("search finds agents across categories", async () => {
    vi.spyOn(api, "listCustomAgents").mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Developers")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Search agents"), { target: { value: "ui" } });
    expect(screen.getByText("Frontend Dev")).toBeInTheDocument();
    expect(screen.queryByText("Testing")).not.toBeInTheDocument();
  });

  it("creates an agent with the chosen tools", async () => {
    vi.spyOn(api, "listCustomAgents").mockResolvedValue([]);
    const create = vi.spyOn(api, "createCustomAgent").mockResolvedValue({
      id: 1, name: "Readme Checker", purpose: "x", tools: [], capabilities: [], createdBy: null, createdAt: null,
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Create Agent/ }));
    await waitFor(() => expect(screen.getByLabelText("read_file")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Readme Checker" } });
    fireEvent.change(screen.getByLabelText("What should it do?"), {
      target: { value: "Check that the README explains setup." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0]?.[0]).toMatchObject({
      name: "Readme Checker",
      tools: ["read_file", "list_files", "search_code"],
    });
  });

  it("lists the user's agents with run and delete", async () => {
    vi.spyOn(api, "listCustomAgents").mockResolvedValue([
      { id: 5, name: "Readme Checker", purpose: "Checks the README.", tools: ["read_file"], capabilities: [], createdBy: null, createdAt: null },
    ]);
    const del = vi.spyOn(api, "deleteCustomAgent").mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() => expect(screen.getByText("Readme Checker")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Open & run" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalled());
    expect(del.mock.calls[0]?.[0]).toBe(5);
  });
});
