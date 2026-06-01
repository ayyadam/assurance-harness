# CI failure triage — ayyadam/testing-system

_Run: 2026-06-01 • window: last 30 days • model: `qwen2.5:32b-instruct-q4_K_M`_

## Summary

Scanned 5 failed run(s) in the window; extracted 5 failure(s); clustered into **5 group(s)** by `(test path, test name, error class)`.

| # | Cluster signature | Members | Category | R-ID |
|---|---|---|---|---|
| 1 | `functional/test_booking_assistant.py::test_assistant_interprets_request_and_books_a_slot` → `playwright._impl._errors.TimeoutError` | 1 | flake | R-018 |
| 2 | `Lint (ruff)::ruff format check` → `<step-failure>` | 1 | defect | — |
| 3 | `functional/test_member_journey.py::test_member_books_a_tee_time` → `AssertionError` | 1 | flake | R-018 |
| 4 | `Performance (k6)::Run k6 load test` → `<step-failure>` | 1 | defect | R-007 |
| 5 | `Contract Tests (Schemathesis)::Run contract tests` → `<step-failure>` | 1 | defect | R-006 |

## Clusters

### 1. test_assistant_interprets_request_and_books_a_slot — `playwright._impl._errors.TimeoutError`

**Test path:** `functional/test_booking_assistant.py`

**Category:** `flake` • **Candidate risk:** `R-018`

**Why:** The failure is a TimeoutError in the functional test `test_assistant_interprets_request_and_books_a_slot`, which matches the symptom described in R-018. The timeout error suggests that the test is flaking due to timing issues, likely related to the cold-container runner environment.

**Action:** Rerun the failed job to confirm if it passes on a subsequent attempt. If it continues to fail, investigate further by checking the container startup times and ensuring that the global expect timeout and page.wait_for_url settings are correctly applied.

**Members (1):**

- [run #31](https://github.com/ayyadam/testing-system/actions/runs/26761531329) — 2026-06-01 14:33 UTC — `push` on `dev` @ `eb50ba1` — R-018 — fix functional flake; relocate nonfunctional reports/ (#13)

**Representative error:** `Timeout 30000ms exceeded.`

### 2. Lint (ruff)::ruff format check — `<step-failure>`

**Category:** `defect` • **Candidate risk:** _none in register_

**Why:** The error message indicates that there are files that would be reformatted by `ruff`, which suggests a code formatting issue rather than an infrastructure or environment problem. This is likely due to unformatted code being pushed, causing the lint check to fail.

**Action:** Run `uv run ruff format` locally before pushing the next commit to ensure all files are properly formatted and pass the lint check.

**Members (1):**

- [run #23](https://github.com/ayyadam/testing-system/actions/runs/26752809643) — 2026-06-01 11:43 UTC — `pull_request` on `feature/phase-8-deterministic-eval` @ `aaf81e9` — Phase 8 deterministic v1 — AI evaluation harness for the booking assistant

**Representative error:** `2 files would be reformatted, 13 files already formatted`

### 3. test_member_books_a_tee_time — `AssertionError`

**Test path:** `functional/test_member_journey.py`

**Category:** `flake` • **Candidate risk:** `R-018`

**Why:** The failure is an AssertionError in the functional test `test_member_books_a_tee_time`, indicating that the expected URL after a navigation action did not match. This matches the symptoms described in R-018, where functional tests flake due to timing issues on cold-container runners.

**Action:** Rerun the failed job to see if it passes on retry, as this is likely a timing issue.

**Members (1):**

- [run #18](https://github.com/ayyadam/testing-system/actions/runs/26601157673) — 2026-05-28 20:44 UTC — `push` on `dev` @ `73eea6e` — Phase 6: data-quality checks (pandera) + CI gate (#7)

**Representative error:** `Page URL expected to be 're.compile('/member/dashboard')'`

### 4. Performance (k6)::Run k6 load test — `<step-failure>`

**Category:** `defect` • **Candidate risk:** `R-007`

**Why:** The error message indicates that the thresholds for 'http_req_duration' and 'http_req_duration{endpoint:tee-times}' have been crossed, which aligns with R-007. This risk is related to performance baselines and regressions in latency or throughput.

**Action:** Investigate recent changes that might affect the performance of the tee-times endpoint and verify if there are any code changes causing this regression.

**Members (1):**

- [run #14](https://github.com/ayyadam/testing-system/actions/runs/26584591354) — 2026-05-28 15:30 UTC — `pull_request` on `feature/perf-k6` @ `605752d` — Phase 5b: performance budgets (k6) + CI gate

**Representative error:** `time="2026-05-28T15:32:14Z" level=error msg="thresholds on metrics 'http_req_duration, http_req_duration{endpoint:tee-times}' have been crossed"`

### 5. Contract Tests (Schemathesis)::Run contract tests — `<step-failure>`

**Category:** `defect` • **Candidate risk:** `R-006`

**Why:** The error message indicates that one of the contract tests failed, which aligns with R-006's risk of no service-boundary contract verification for the JSON API. This suggests a real bug in the SUT or harness where there is a mismatch between the schema and actual behavior.

**Action:** Investigate the specific failing test case within the contract tests to identify any discrepancies between the expected schema and the actual API response.

**Members (1):**

- [run #7](https://github.com/ayyadam/testing-system/actions/runs/26576683927) — 2026-05-28 13:09 UTC — `pull_request` on `feature/contract-tests` @ `b83ff61` — Phase 4: Schemathesis API contract tests

**Representative error:** `=============== 1 failed, 1 passed, 5 subtests passed in 12.37s ================`

---

_Generated by `triage_agent` (phase 10). Advisory — clusters are a starting point for the on-call reviewer, not a categorisation gate. See [`triage_agent/README.md`](../README.md)._
