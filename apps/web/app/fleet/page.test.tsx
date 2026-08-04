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
