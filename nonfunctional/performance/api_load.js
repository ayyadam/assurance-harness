// Performance budget for golf-web-app's read-path API (service boundary).
//
// This is a small, fast load profile suitable for a per-PR gate: it ramps to
// a modest concurrency, exercises the read endpoints, and FAILS the run
// (non-zero exit) if any threshold is breached. The thresholds ARE the budget
// — a regression beyond them turns the CI job red.
//
// The read endpoints require bearer auth (golf-web-app PR #15). setup() runs
// once per run, exchanges seeded credentials for a bearer token, and the
// per-VU iterations send it. The token costs one POST per run — negligible
// against a 35-second ramp/hold/cool-down.
//
// Run against a live SUT (default http://localhost:5000):
//   k6 run nonfunctional/performance/api_load.js
//   SUT_BASE_URL=http://host.docker.internal:5000 \
//     docker run --rm -i -e SUT_BASE_URL -v "$PWD:/work" -w /work \
//     grafana/k6 run nonfunctional/performance/api_load.js

import http from "k6/http";
import { check, group, sleep, fail } from "k6";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.1.0/index.js";

const BASE_URL = __ENV.SUT_BASE_URL || "http://localhost:5000";
const USERNAME = __ENV.SUT_USERNAME || "john.smith";
const PASSWORD = __ENV.SUT_PASSWORD || "Password1";

export const options = {
  scenarios: {
    api_reads: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "10s", target: 10 }, // ramp up
        { duration: "20s", target: 10 }, // hold
        { duration: "5s", target: 0 }, // ramp down
      ],
    },
  },
  // Budget-as-code. p95 latency well clear of any human-perceptible delay,
  // with margin for shared CI runners; near-zero error rate.
  thresholds: {
    http_req_failed: ["rate<0.01"], // < 1% of requests may fail
    http_req_duration: ["p(95)<500"], // overall p95 < 500ms
    "http_req_duration{endpoint:tee-times}": ["p(95)<500"],
    "http_req_duration{endpoint:competitions}": ["p(95)<500"],
    checks: ["rate>0.99"], // > 99% of status checks pass
  },
};

// setup() runs once per k6 run; its return value is passed as `data` to
// every VU iteration. We exchange seeded credentials for a bearer token here
// and reuse it for the duration of the run. A token-acquisition failure here
// fails the whole run immediately rather than reporting it as 401 noise on
// every iteration.
export function setup() {
  const res = http.post(
    `${BASE_URL}/api/v1/auth/token`,
    JSON.stringify({ username: USERNAME, password: PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  );
  if (res.status !== 200) {
    fail(`setup: /auth/token returned ${res.status} — cannot run load`);
  }
  return { token: res.json("access_token") };
}

export default function (data) {
  const params = {
    headers: { Authorization: `Bearer ${data.token}` },
  };

  group("tee-times list", () => {
    const res = http.get(`${BASE_URL}/api/v1/tee-times`, {
      headers: params.headers,
      tags: { endpoint: "tee-times" },
    });
    check(res, { "tee-times -> 200": (r) => r.status === 200 });
  });

  group("competitions list", () => {
    const res = http.get(`${BASE_URL}/api/v1/competitions`, {
      headers: params.headers,
      tags: { endpoint: "competitions" },
    });
    check(res, { "competitions -> 200": (r) => r.status === 200 });
  });

  sleep(1);
}

// Write a machine-readable summary for CI evidence; keep the readable summary
// on stdout so the job log shows the percentiles at a glance.
export function handleSummary(data) {
  return {
    stdout: textSummary(data, { indent: " ", enableColors: false }),
    "nonfunctional/reports/perf/summary.json": JSON.stringify(data, null, 2),
  };
}
