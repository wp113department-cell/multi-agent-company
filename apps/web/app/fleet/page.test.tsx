import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FleetDashboardPage from "./page";
import * as auth from "../../lib/auth";

const EMPTY_REQUESTS_RESPONSE = new Response(JSON.stringify([]), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

const HEALTH_RESPONSE = [
  {
    agentName: "coder",
    totalRuns: 40,
    failedRuns: 4,
    failureRate: 0.1,
    activeRuns: 2,
    avgHeartbeatStalenessSeconds: 12.3,
  },
  {
    agentName: "qa",
    totalRuns: 10,
    failedRuns: 0,
    failureRate: 0.0,
    activeRuns: 0,
    avgHeartbeatStalenessSeconds: null,
  },
];

class FakeEventSource {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(_url: string) {}
}

describe("FleetDashboardPage — Q119 real active-agent health wiring", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.spyOn(auth, "authHeaders").mockReturnValue({});
    vi.spyOn(auth, "isApprover").mockReturnValue(true);
  });

  it("fetches and renders the real /api/fleet/reports/health data as an Agent Health table", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/fleet/requests") {
        return Promise.resolve(EMPTY_REQUESTS_RESPONSE.clone());
      }
      if (url === "/api/fleet/reports/health") {
        return Promise.resolve(
          new Response(JSON.stringify(HEALTH_RESPONSE), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<FleetDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Agent Health")).toBeInTheDocument();
    });
    expect(screen.getByText("coder")).toBeInTheDocument();
    expect(screen.getByText("qa")).toBeInTheDocument();
    expect(screen.getByText("10.0%")).toBeInTheDocument(); // coder failure rate
    expect(screen.getByText("12.3s")).toBeInTheDocument(); // coder staleness
    expect(screen.getByText("—")).toBeInTheDocument(); // qa has no active runs / null staleness

    expect(fetchMock).toHaveBeenCalledWith("/api/fleet/reports/health", expect.anything());
  });

  it("does not render the Agent Health section when the health fetch fails, and doesn't clobber the main error banner", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/fleet/requests") {
        return Promise.resolve(EMPTY_REQUESTS_RESPONSE.clone());
      }
      if (url === "/api/fleet/reports/health") {
        return Promise.reject(new Error("network down"));
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<FleetDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/Nothing to review right now/i)).toBeInTheDocument();
    });
    expect(screen.queryByText("Agent Health")).not.toBeInTheDocument();
    expect(screen.queryByText("network down")).not.toBeInTheDocument();
  });
});

describe("FleetDashboardPage — AUDIT_Q_BATCH07 §12/§64 autoApplicable surfacing", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.spyOn(auth, "authHeaders").mockReturnValue({});
    vi.spyOn(auth, "isApprover").mockReturnValue(true);
  });

  const baseRequest = {
    id: 1,
    agentName: "architecture_reviewer",
    title: "Dead code found in app/foo.py",
    description: "Unused function bar()",
    category: "architecture",
    priority: "low" as const,
    evidence: {},
    filesTouched: [],
    commitSha: null,
    restartRequired: false,
    error: null,
    traceId: null,
    createdAt: new Date().toISOString(),
    decidedAt: null,
    decidedBy: null,
    completedAt: null,
  };

  function stubRequests(requests: unknown[]): void {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/fleet/requests") {
        return Promise.resolve(
          new Response(JSON.stringify(requests), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );
      }
      if (url === "/api/fleet/reports/health") {
        return Promise.resolve(EMPTY_REQUESTS_RESPONSE.clone());
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
  }

  it('shows a "Recommendation only" badge on a pending request from an agent with no apply phase', async () => {
    stubRequests([{ ...baseRequest, status: "pending", autoApplicable: false }]);

    render(<FleetDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Recommendation only")).toBeInTheDocument();
    });
  });

  it("does not show the badge for a pending request from an agent with a real apply phase", async () => {
    stubRequests([
      { ...baseRequest, agentName: "agent_debugger", status: "pending", autoApplicable: true },
    ]);

    render(<FleetDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(baseRequest.title)).toBeInTheDocument();
    });
    expect(screen.queryByText("Recommendation only")).not.toBeInTheDocument();
  });

  it("explains a completed no-apply-phase request instead of implying code changed", async () => {
    stubRequests([
      {
        ...baseRequest,
        status: "completed",
        autoApplicable: false,
        decidedAt: new Date().toISOString(),
        completedAt: new Date().toISOString(),
      },
    ]);

    render(<FleetDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/no automated apply phase, so no code was changed/i)).toBeInTheDocument();
    });
  });
});
