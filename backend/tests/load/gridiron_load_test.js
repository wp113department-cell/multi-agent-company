/*
 * Gap-closure Day 55-56 (Stage 2, answers.md Q11 "Load Tests"/"Stress Tests":
 * NO — no locust/k6/or equivalent load-generation tooling found anywhere in
 * the repo). A real k6 script against this platform's own real, read-only
 * FastAPI endpoints — not against an external target, and not a script
 * generated on request by the existing load_test_agent.py (which produces
 * ad-hoc scripts for arbitrary target repos, never committed here for the
 * platform's own infrastructure).
 *
 * Endpoints exercised (all confirmed real by reading their route handlers,
 * not guessed):
 *   GET /health              — app/main.py::health(), no auth
 *   GET /api/agents          — app/api/registry.py::list_agents(), no auth
 *   GET /api/metrics         — app/api/metrics.py::get_system_metrics(), requires
 *                               auth when JWT_AUTH_ENABLED=true (set API_TOKEN;
 *                               AUDIT_Q_BATCH06 §9 gap-closure added
 *                               require_authenticated here)
 *   GET /api/tasks           — app/api/tasks.py::list_all(), requires auth
 *                               when JWT_AUTH_ENABLED=true (set API_TOKEN)
 *
 * Usage:
 *   k6 run tests/load/gridiron_load_test.js                       # load profile
 *   k6 run -e SCENARIO=stress tests/load/gridiron_load_test.js     # stress profile
 *   k6 run -e BASE_URL=http://localhost:8000 -e API_TOKEN=... tests/load/gridiron_load_test.js
 *
 * Zero hardcoding: BASE_URL/API_TOKEN/SCENARIO are all env-driven, never a
 * baked-in deployment URL or credential.
 */

import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_TOKEN = __ENV.API_TOKEN || "";
const SCENARIO = __ENV.SCENARIO || "load";

const authHeaders = API_TOKEN
  ? { Authorization: `Bearer ${API_TOKEN}` }
  : {};

// Load profile: a realistic steady ramp — establishes baseline throughput
// and latency under expected traffic (Q11's "Load Tests").
const LOAD_STAGES = [
  { duration: "20s", target: 10 },
  { duration: "40s", target: 10 },
  { duration: "10s", target: 0 },
];

// Stress profile: ramps well past the load profile's peak to find the real
// breaking point (Q11's "Stress Tests") — a distinct traffic shape from
// load, not just "run load longer".
const STRESS_STAGES = [
  { duration: "20s", target: 25 },
  { duration: "30s", target: 75 },
  { duration: "30s", target: 150 },
  { duration: "20s", target: 0 },
];

export const options = {
  scenarios: {
    [SCENARIO]: {
      executor: "ramping-vus",
      exec: "default",
      startVUs: 0,
      stages: SCENARIO === "stress" ? STRESS_STAGES : LOAD_STAGES,
    },
  },
  thresholds:
    SCENARIO === "stress"
      ? {
          // Stress mode is expected to approach/exceed comfortable latency —
          // the threshold here is a sanity ceiling (never fully unresponsive
          // or majority-failing), not a "still fast" bar.
          http_req_duration: ["p(95)<3000"],
          http_req_failed: ["rate<0.10"],
        }
      : {
          // Load mode's explicit pass/fail bar for normal expected traffic.
          http_req_duration: ["p(95)<500"],
          http_req_failed: ["rate<0.01"],
        },
};

export default function () {
  const health = http.get(`${BASE_URL}/health`);
  check(health, {
    "/health status is 200": (r) => r.status === 200,
    "/health body has status field": (r) => {
      try {
        return typeof JSON.parse(r.body).status === "string";
      } catch (e) {
        return false;
      }
    },
  });

  const agents = http.get(`${BASE_URL}/api/agents`);
  check(agents, {
    "/api/agents status is 200": (r) => r.status === 200,
    "/api/agents body is an array": (r) => {
      try {
        return Array.isArray(JSON.parse(r.body));
      } catch (e) {
        return false;
      }
    },
  });

  const metrics = http.get(`${BASE_URL}/api/metrics`, { headers: authHeaders });
  check(metrics, {
    "/api/metrics status is 200 or 401": (r) => r.status === 200 || r.status === 401,
  });

  const tasks = http.get(`${BASE_URL}/api/tasks`, { headers: authHeaders });
  check(tasks, {
    "/api/tasks status is 200 or 401": (r) =>
      r.status === 200 || r.status === 401,
    "/api/tasks body has tasks field when authorized": (r) => {
      if (r.status !== 200) return true; // 401 without a token is expected/OK
      try {
        return Array.isArray(JSON.parse(r.body).tasks);
      } catch (e) {
        return false;
      }
    },
  });

  sleep(1);
}
