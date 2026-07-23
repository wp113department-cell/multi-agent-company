import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import AgentRegistryPage from "./page";
import * as api from "@/lib/api";

const SAMPLE_AGENTS: api.AgentRegistryEntry[] = [
  {
    agentId: "1",
    name: "architect",
    capabilityTags: ["design", "architecture", "read_only"],
    toolList: ["read_file", "list_files", "submit_plan"],
    promptRef: "roles/architect.md",
    version: "1.0",
    successRate: 1.0,
    avgRetries: 0.0,
    lastComputedAt: "2026-07-09T12:25:21Z",
    createdAt: "2026-07-09T12:25:21Z",
  },
  {
    agentId: "2",
    name: "backend_dev",
    capabilityTags: ["code", "backend", "python"],
    toolList: ["read_file", "write_file", "bash", "git_diff", "submit_patch"],
    promptRef: "roles/backend_dev.md",
    version: "1.0",
    successRate: 0.5,
    avgRetries: 1.5,
    lastComputedAt: "2026-07-09T12:25:21Z",
    createdAt: "2026-07-09T12:25:21Z",
  },
];

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("AgentRegistryPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a loading state before the fetch resolves", () => {
    vi.spyOn(api, "fetchAgents").mockReturnValue(new Promise(() => {}));
    renderWithQueryClient(<AgentRegistryPage />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders one row per agent once loaded", async () => {
    vi.spyOn(api, "fetchAgents").mockResolvedValue(SAMPLE_AGENTS);
    renderWithQueryClient(<AgentRegistryPage />);

    await waitFor(() => {
      expect(screen.getByText("architect")).toBeInTheDocument();
    });
    expect(screen.getByText("backend_dev")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3); // 1 header + 2 agents
  });

  it("shows the KPI summary computed from the real agent list", async () => {
    vi.spyOn(api, "fetchAgents").mockResolvedValue(SAMPLE_AGENTS);
    renderWithQueryClient(<AgentRegistryPage />);

    await waitFor(() => {
      expect(screen.getByText("Registered agents")).toBeInTheDocument();
    });
    // 2 agents registered
    expect(screen.getByText("2")).toBeInTheDocument();
    // avg success rate = (1.0 + 0.5) / 2 = 75.0%
    expect(screen.getByText("75.0%")).toBeInTheDocument();
  });

  it("filters by capability tag", async () => {
    vi.spyOn(api, "fetchAgents").mockResolvedValue(SAMPLE_AGENTS);
    renderWithQueryClient(<AgentRegistryPage />);

    await waitFor(() => {
      expect(screen.getByText("architect")).toBeInTheDocument();
    });

    const select = screen.getByLabelText(/capability/i);
    fireEvent.change(select, { target: { value: "backend" } });

    await waitFor(() => {
      expect(screen.queryByText("architect")).not.toBeInTheDocument();
    });
    expect(screen.getByText("backend_dev")).toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.spyOn(api, "fetchAgents").mockRejectedValue(new Error("boom"));
    renderWithQueryClient(<AgentRegistryPage />);

    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });

  it("shows an empty state with zero agents", async () => {
    vi.spyOn(api, "fetchAgents").mockResolvedValue([]);
    renderWithQueryClient(<AgentRegistryPage />);

    await waitFor(() => {
      expect(screen.getByText(/no agents registered yet/i)).toBeInTheDocument();
    });
  });
});
