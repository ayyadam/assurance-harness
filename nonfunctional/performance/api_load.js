// Performance budget for golf-web-app's read-path API (service boundary).
//
// This is a small, fast load profile suitable for a per-PR gate: it ramps to
// a modest concurrency, exercises the public read endpoints, and FAILS the run
// (non-zero exit) if any threshold is breached. The thresholds ARE the budget
// — a regression beyond them turns the CI job red.
//
// Run against a live SUT (default http://localhost:5000):
//   k6 run nonfunctional/performance/api_load.js
//   SUT_BASE_URL=http://host.docker.internal:5000 \
//     docker run --rm -i -e SUT_BASE_URL -v "$PWD:/work" -w /work \
//     grafana/k6 run nonfunctional/performance/api_load.js

import http from "k6/http";
import { check, group, sleep } from "k6";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.1.0/index.js";

const BASE_URL = __ENV.SUT_BASE_URL || "http://localhost:5000";

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

export default function () {
  group("tee-times list", () => {
    const res = http.get(`${BASE_URL}/api/v1/tee-times`, {
      tags: { endpoint: "tee-times" },
    });
    check(res, { "tee-times -> 200": (r) => r.status === 200 });
  });

  group("competitions list", () => {
    const res = http.get(`${BASE_URL}/api/v1/competitions`, {
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
    "reports/perf/summary.json": JSON.stringify(data, null, 2),
  };
}
