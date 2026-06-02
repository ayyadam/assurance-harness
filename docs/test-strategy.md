# Test Strategy — golf-web-app

**Status:** living document — updated as the assurance harness matures.
**Owner:** Adam (acting as Digital Assurance Engineer)
**Last updated:** 2026-06-02 *(F-012 — R-018 root-cause fix)*

---

## 1. Purpose

This document describes how we assure the quality of [golf-web-app](https://github.com/ayyadam/golf-web-app) — the system under test — using the [testing-system](https://github.com/ayyadam/testing-system) harness. It exists to:

- Make our assurance approach explicit so delivery decisions can be informed by it
- Give a hiring panel reviewing this portfolio a clear picture of *judgement*, not just tooling
- Provide a stable reference that newer artifacts (test suites, dashboards, reports) link back to

It is deliberately a *living* document — every phase of work updates the relevant section and adds findings to §11.

## 2. System under test

`golf-web-app` is a Flask + SQLAlchemy + Postgres web application for managing a golf club: tee-time bookings, competitions, coaching, range bays, and membership requests. Server-rendered Jinja templates with Bootstrap, Flask-Login for authentication, Docker Compose for the local stack, GitHub Container Registry for image distribution.

Two additions extend the assurance surface:

- A small JSON API (`/api/v1/...`) so service-boundary contract testing has something to assert against — **delivered** (phase 2)
- A natural-language booking feature backed by a local LLM (Ollama) so the AI-evaluation harness has something real to evaluate — **delivered** (phase 7). The feature follows an *interpret-and-propose* design: the model only extracts a structured intent from free text; deterministic code validates it and proposes genuinely bookable slots, and the member confirms. The model never books — that boundary is the control against hallucinated or injected instructions.

## 3. Goals and non-goals

**Goals**

- Catch defects before they reach `master`, with fast and useful feedback in CI
- Verify the system at meaningful boundaries (user journey, API contract, data shape, deployability), not at the line-coverage level
- Produce durable evidence (reports, dashboards, written findings) that delivery teams and reviewers can consume without running the code
- Embed assurance perspective into design discussions early, not as a gate at the end
- Demonstrate that AI/agentic capabilities can be applied to assurance work where determinism is expensive

**Non-goals**

- 100% line coverage as an end in itself
- Full production deployment — golf-web-app is not user-facing software; smoke-testing deployability is sufficient
- Replacing developer judgement with autoformatters or LLMs — both are tools, not decisions

## 4. Principles

1. **Risk-based prioritisation.** We test what matters most. The [risk register](risk-register.md) drives this, not coverage targets.
2. **Service-boundary assertions.** Tests target the boundaries that real change-makers cross — user journeys, API contracts, data shapes — not implementation detail.
3. **Fast and meaningful feedback.** A CI run that takes 20 minutes and ends "lint passed, tests passed, smoke passed" earns less trust than a 3-minute run that prints "1 contract test failed: `POST /api/v1/bookings` accepts `group_size < 1`."
4. **Evidence as a first-class output.** Test reports, JUnit artifacts, GHCR images, and findings logged in this document are the *product* of assurance, not by-products.
5. **Determinism for gates, agents for judgement.** Pass/fail in CI stays deterministic. LLM-judges, exploratory agents, and risk-prioritisation agents earn their keep on tasks where determinism is too expensive (semantic evaluation, exploration, triage) — not on pass/fail gates.
6. **Treat findings as artifacts.** Every assurance failure that *would have surprised someone* is captured in §11 with a short case study. The story of the work is part of the work.

## 5. Test layers

Layers planned across the project. Each layer has an explicit "why this exists" — layers without one don't earn their place.

| Layer | Status | Tooling | Lives in | Purpose |
|---|---|---|---|---|
| Unit (in-process) | **Done** | pytest | `golf-web-app/tests/unit/` | Fast, deterministic coverage of services, models, route handlers |
| Integration (Postgres-backed) | **Done** | pytest + Postgres service container | `golf-web-app/tests/unit/` (same suite, real DB) | Catch defects that depend on real DB behaviour (FK enforcement, transaction semantics) — SQLite locally hides these |
| Deployability smoke | **Done** | Docker Compose health check | `golf-web-app/.github/workflows/ci-cd.yml` | Prove the production stack starts cleanly and serves `/` on every push |
| Contract | **Done** | Schemathesis vs OpenAPI | `testing-system/contract/` | Verify the JSON API conforms to its spec under property-based inputs |
| UI / E2E journeys | **Done** | Playwright + pytest | `testing-system/functional/` | Exercise the booking journey, the natural-language booking assistant, and access-control boundaries in a real browser, as a member experiences them |
| Accessibility | **Done** | axe-core (axe-playwright-python) | `testing-system/nonfunctional/accessibility/` | WCAG 2.1 A/AA sweep of key pages; gate the PR on serious + critical violations, track the rest |
| Performance | **Done** | k6 (thresholds-as-code) | `testing-system/nonfunctional/performance/` | Latency/error budgets on the read-path API; fail the PR on regression beyond budget |
| Data quality | **Done** | pandera (schemas + invariants) | `testing-system/data_quality/` | Validate the live database against column contracts and business-rule invariants (e.g. 18 holes with a 1..18 stroke-index permutation) |
| AI evaluation | **Done (phase 8 v1)** | Black-box golden-set scoring (deterministic + LLM-judge) | [`testing-system/ai_evaluation/`](../ai_evaluation/README.md) | Quantifies model accuracy, safety, latency across a model list. Two grading tiers — deterministic field equality + an LLM-judge (holistic 0-10 + per-rubric fuzzy pass/fail). Current 5-model report: [`ai_evaluation/reports/report.md`](../ai_evaluation/reports/report.md) |
| Risk-prioritisation (advisory) | **Done (phase 9 v2 v2)** | Local Ollama agent + deterministic post-processing + golden-set eval | [`testing-system/risk_agent/`](../risk_agent/README.md) | Given a PR diff + the live risk register, produces a ranked test plan with `covered_by` per risk, coverage-gap flags, relevance label (`direct` / `plausible`), and exploratory probes. Advisory only, not a CI gate. v2 v1 made `covered_by` and `is_gap` deterministic; v2 v2 added a golden-set evaluation tier ([`risk_agent.eval`](../risk_agent/eval.py)) that scores the agent against expected ranks per historic PR (precision, recall, F1 — deterministic, no LLM in scoring). Current baseline: F1 0.526 (precision 0.417 / recall 0.714) across 4 cases. The baseline is the deliverable — future changes are now scored against measurable numbers. See [`risk_agent/reports/eval-report.md`](../risk_agent/reports/eval-report.md) |
| Triage (advisory) | **Done (phase 10 v1 v2)** | Local Ollama agent over `gh` log dumps + golden-set eval | [`testing-system/triage_agent/`](../triage_agent/README.md) | Clusters failed CI runs by signature `(test path, test name, error class)`, then asks the LLM for a category (flake / defect / infra / env) and a candidate register R-ID per cluster. Closed-vocabulary enum on the R-ID — the model cannot invent risks. v1 v2 added a golden-set evaluation tier ([`triage_agent.eval`](../triage_agent/eval.py)) scoring the agent against expected (category, R-ID) per known cluster — deterministic, no LLM in scoring. Current baseline: 5/5 on category, R-ID, and combined. Historical insight from v1 v1: R-018 was actually present at run #18 (2026-05-28), three weeks before it was logged. See [`triage_agent/reports/report.md`](../triage_agent/reports/report.md) and [`triage_agent/reports/eval-report.md`](../triage_agent/reports/eval-report.md) |
| Production observability | **Done (phase 11 v1)** | Prometheus + Grafana (metrics only; Loki + Alertmanager v2 candidates) | [`testing-system/observability/`](../observability/README.md) | Local stack scraping the SUT's `/metrics` (provisioned by `prometheus-flask-exporter`), provisioned dashboard with request rate / error rate / p95 latency / per-path breakdowns. SLO thresholds on the dashboard match the k6 perf gate's pre-merge budget — same SLOs, two enforcement points. Closes R-013. See [`observability/README.md`](../observability/README.md) and [`observability/evidence/grafana-sut-overview.png`](../observability/evidence/grafana-sut-overview.png) |
| Exploratory (advisory) | **Done (phase 12 v2 v1)** | Local Ollama agent — API surface via OpenAPI, UI surface via Playwright, deterministic eval tier | [`testing-system/explore_agent/`](../explore_agent/README.md) | Two surfaces share the same package and the same closed-enum + LLM-jury pattern. **API** (`explore_agent.run`, v1 v1): every v1 endpoint probed with three LLM-generated payload variants (happy / edge / abusive, including prompt-injection on AI endpoints), responses classified into `expected` / `unexpected_5xx` / `schema_drift` / `business_rule_concern`. **UI** (`explore_agent.ui_run`, v1 v2): three predefined tours, each with an LLM-planned step sequence executed in Playwright, per-step state captured and LLM-judged into `expected` / `unexpected_5xx` / `js_error` / `dead_end` / `business_rule_concern`. **Eval** (`explore_agent.eval`, v2 v1): golden-set evaluation tier mirroring [`risk_agent.eval`](../risk_agent/eval.py) and [`triage_agent.eval`](../triage_agent/eval.py) — deterministic scoring against expected category per (endpoint, variant), no LLM in the scoring path. **Baseline: 50.0% accuracy (9/18 cases)** — every case's expected category is `expected` (no defects in the seeded surface) and the agent over-flags 9 of them (7 as `business_rule_concern`, 2 as `unexpected_5xx`). This quantifies the documented v1 v1 over-flagging behaviour and gives a measurable target for any future judge-prompt tightening or model swap. v1 v2's UI agent also surfaced the *plan-once-from-starting-page* limitation cleanly (LLM hallucinated `.candidate-slot` when the actual class was `.booking-slot`); the architectural fix (adaptive single-step) is tracked in the [phase-12 sub-roadmap](#phase-12-sub-roadmap), with the eval baseline as its decision input. Both probing surfaces remain local-only (cost-prohibitive for CI); the eval is also local-only. See [`explore_agent/reports/report.md`](../explore_agent/reports/report.md) (API), [`explore_agent/reports/ui/report.md`](../explore_agent/reports/ui/report.md) (UI), [`explore_agent/reports/eval-report.md`](../explore_agent/reports/eval-report.md) (eval). |
| Tests of the harness itself | **In progress (phase 12 v2 v2)** | pytest (LLM-gated via `RUN_AGENT_REGRESSION=1`) | [`testing-system/tests/agents/`](../tests/agents/README.md) | Adversarial regression suite for `risk_agent` and `triage_agent`: each agent invoked N=3 times against cached fixtures, with hard invariants (schema validity, closed-vocabulary on every emitted R-ID, relevance in {2, 3}), soft invariants (top-result stability ≥ 0.66 across runs), and a **stable-divergent warning** (test still passes, but emits a `StableDivergentWarning` and flags the case in the rendered report when the agent's stable answer disagrees with the golden set's expected top-1). The eval tiers measure *accuracy*; this measures *stability under LLM jitter* and surfaces stable-but-wrong cases that single-run eval averages can hide. Baseline run (all 4 cases): 12/12 schema-valid, 12/12 closed-vocab, 100% stability — and one stable-divergent warning on `risk_agent` PR #12. The warning case ([details](../tests/agents/README.md#notable-findings-from-the-baseline-run)) traces to a model error confirmed by a model-swap experiment (qwen2.5:32b and 14b both over-pull R-002 with near-identical rationale), so the fix lives in prompt or register framing — tracked as a [phase 9 v3 follow-up](#phase-12-sub-roadmap). Local-only — LLM calls would flake CI. See [`tests/agents/reports/regression-report.md`](../tests/agents/reports/regression-report.md) |

A traditional test pyramid does not map cleanly onto this project because the SUT is one of several concerns alongside data quality, AI evaluation, and observability. The above is a *responsibility map*, not a pyramid.

## 6. Tooling

| Tool | Purpose | Adopted? |
|---|---|---|
| Python 3.12 | Language runtime for both SUT and harness | Yes |
| `uv` | Dependency and venv management for testing-system | Yes |
| pip + venv | Dependency management for golf-web-app (pre-existing) | Yes |
| pytest | Test runner everywhere | Yes |
| ruff | Lint + format for testing-system | Yes |
| flake8 | Lint for golf-web-app (pre-existing; ruff migration deferred) | Yes |
| Playwright | UI / E2E browser automation | Yes |
| Schemathesis | Property-based API contract testing | Yes |
| k6 | Performance load generation (thresholds-as-code) | Yes |
| axe-core (axe-playwright-python) | Accessibility checks (WCAG 2.1 A/AA) | Yes |
| pandera | Data quality (schemas + business invariants) | Yes |
| GitHub Actions | CI/CD on both repos | Yes |
| GHCR | Container artifact storage | Yes |
| Prometheus + Grafana | Production-style observability | Yes (phase 11 v1) |

## 7. CI/CD integration

Two pipelines, two repos, distinct responsibilities.

**`golf-web-app/.github/workflows/ci-cd.yml`** — verifies its own code. Triggers on push and PR to `master` and `develop`.
- Lint (flake8) — must pass
- Unit tests (pytest against Postgres service container) — must pass
- Deployability smoke test (compose up, health check on `/`) — must pass
- Build and publish image to GHCR (`ghcr.io/ayyadam/golf-web-app:sha-xxxxxxx`); `:latest` tag only on `master` pushes
- GitHub Release created only on `master` pushes

**`testing-system/.github/workflows/assurance.yml`** — runs the harness. Triggers on push and PR to `master` and `dev`.
- Lint (ruff check + format) — must pass
- Pytest (tests of the harness itself) with JUnit + HTML reports uploaded as artifacts
- Contract tests (Schemathesis) — checks out golf-web-app, brings it up via compose, seeds it, and fuzzes the JSON API against its OpenAPI spec
- Functional tests (Playwright) — same SUT bring-up, then drives the booking and access-control journeys in headless Chromium; screenshots and traces are captured on failure
- Accessibility (axe-core) — same SUT bring-up, then runs the WCAG 2.1 A/AA sweep over key pages and fails on serious + critical violations; per-page axe JSON is uploaded as evidence
- Performance (k6) — same SUT bring-up, then runs a short ramped load against the read-path API; the k6 thresholds are the budget, so a regression beyond them fails the job. Summary JSON is uploaded as evidence
- Data quality (pandera) — same SUT bring-up, then reads the live Postgres tables and validates them against column contracts and business invariants

The contract, functional, accessibility, performance, and data-quality jobs each stand up their own ephemeral SUT from source (compose `up --build` + `seed.py`), so they need no deployed instance. Performance is the one layer not driven by pytest — k6 is its own runner with thresholds-as-code — which is why its budget lives in the k6 script rather than an assertion.

All test reports (JUnit, HTML, coverage) are uploaded as GitHub Actions artifacts and retained per GitHub's defaults (90 days). The downloadable HTML report is the canonical evidence artifact for a given commit.

## 8. Risk-based prioritisation

We test in the order the [risk register](risk-register.md) ranks. A risk's score is `Likelihood × Impact`, with ties broken by reversibility (irreversible failures rank higher than recoverable ones).

Coverage numbers are informational, not target. A 90% covered codebase that doesn't exercise concurrent booking races is less assured than a 70% covered one that does.

## 9. Defect management

Every defect surfaced by the harness — whether by a deterministic check or an exploratory agent — is logged as a GitHub Issue on the SUT repository (`ayyadam/golf-web-app`). Issues use these labels:

- `bug` (default)
- `severity:critical|major|minor`
- `area:auth|booking|admin|...`
- `surfaced-by:ci|exploratory-agent|manual|user-report`

A bug fix PR references the Issue. The Issue is closed by the merge.

Defects found mid-PR (like the SQLite-vs-Postgres finding below) are fixed in the same PR rather than logged separately, with a paragraph in the PR description and a case study added here.

## 10. Evidence

| Artifact | Where | Retention |
|---|---|---|
| Unit test HTML report | GitHub Actions artifact `unit-test-reports` on each run | 90 days |
| Coverage report | Same artifact, `coverage/` subfolder | 90 days |
| Pytest report (harness) | GitHub Actions artifact `pytest-reports` on each run | 90 days |
| Contract test report | GitHub Actions artifact `contract-test-reports` on each run | 90 days |
| Functional test report + Playwright traces/screenshots (on failure) | GitHub Actions artifact `functional-test-reports` on each run | 90 days |
| Accessibility report + per-page axe JSON | GitHub Actions artifact `accessibility-reports` on each run | 90 days |
| Performance summary (k6 metrics JSON) | GitHub Actions artifact `performance-reports` on each run | 90 days |
| Data-quality report | GitHub Actions artifact `data-quality-reports` on each run | 90 days |
| Container image | `ghcr.io/ayyadam/golf-web-app:sha-xxxxxxx` | Indefinite |
| GitHub Release notes | Releases tab on golf-web-app, only for `master` pushes | Indefinite |
| Findings | §11 below | Indefinite (committed to repo) |

## 11. Findings to date

### F-001 — Local SQLite hides foreign-key violations that Postgres catches in CI

**Date:** 2026-05-27
**Surfaced by:** First successful CI run of `chore/ci-pipeline-rework` PR
**Severity:** Major (8 silently-broken tests; pattern would replicate as the suite grows)

The `golf-web-app` test suite was running against in-memory SQLite locally and against a Postgres service container in CI. SQLite does not enforce foreign-key constraints by default; Postgres does. Seven tests were inserting `general_bookings`, `range_bookings`, `coaching_bookings`, and `competition_bookings` rows pointing to hardcoded `visitor_id=1`, `member_id=999`, or `member_id=i+100` values that did not exist in the test database. SQLite silently accepted these; Postgres rejected them with `ForeignKeyViolation`.

**Resolution**
- Added a SQLAlchemy `Engine.connect` event listener to `tests/conftest.py` that enables `PRAGMA foreign_keys=ON` on SQLite connections. Local test runs now match Postgres semantics.
- Added an `other_member` fixture to conftest for "another user" scenarios.
- Updated all seven tests to use proper fixtures (`visitor`, `other_member`) instead of hardcoded ids.
- `test_book_competition_full` now creates three throwaway Member rows inline rather than referencing non-existent ids 100–102.

**Generalisation**
This finding is recorded in the risk register as R-001 with mitigation linked to the conftest change. The class of bug — *test environment more permissive than production environment* — will be a recurring concern as more layers (Playwright against compose, contract against a deployed API) are added.

### F-002 — 82 latent style violations exposed on first lint enforcement

**Date:** 2026-05-27
**Surfaced by:** First successful CI run of `chore/ci-pipeline-rework` PR
**Severity:** Minor (cosmetic + a handful of unused imports/variables)

The `golf-web-app` workflow had a `lint` job configured against flake8 from the project's inception, but the workflow's trigger was incorrectly set to `branches: [main]` and the default branch is `master` — so the workflow had never run. The first run after the trigger was corrected produced 82 violations across 9 files: 48 whitespace-on-blank-lines, 16 unused imports, 7 lines >120 chars, 3 multi-statement-on-one-line, 2 unused locals, 3 spacing issues, 2 unused-name patterns, 1 redefinition.

**Resolution**
- `autopep8 --aggressive --max-line-length=120 --recursive` and `autoflake --remove-all-unused-imports --remove-unused-variables --recursive` resolved 79 of 82 mechanically.
- Three hand-fixes: a long flash message line-wrapped, two unused `resp = ...` assignments dropped.

**Generalisation**
A CI gate that is not actually enforced is worse than no gate, because it implies a level of assurance it does not provide. The lint enforcement is now meaningful and gates merges. (See R-005 in the risk register.)

### F-003 — Contract testing surfaced five spec-vs-behaviour mismatches

**Date:** 2026-05-28
**Surfaced by:** First run of the Schemathesis contract suite (`contract/`) against the running Postgres-backed API
**Severity:** Mixed (one 500 crash; the rest contract/documentation defects)

The v1 JSON API shipped with an auto-generated OpenAPI spec, but property-based contract testing proved the spec documented happy paths while the real API diverged in five ways:

1. **Wrong status semantics.** Business-state rejections (past tee time, full, already booked) returned `400 Bad Request`; these are conflicts with current state, corrected to `409 Conflict`.
2. **Type mismatch.** `MemberOut.handicap` serialized as a string (`"12.3"`) while the spec declared `number`. Switched to a float field.
3. **Invalid timestamp format.** `booked_at` was a naive datetime with no offset — not a valid RFC 3339 `date-time`. Now emitted as UTC with a `Z` suffix.
4. **Undocumented status code.** Malformed JSON bodies return `400`, undocumented on the token and booking endpoints. Now documented.
5. **500 crash.** Input containing lone surrogate characters crashed the auth endpoint (psycopg2 cannot encode them). Added a UTF-8 validator so such input is rejected cleanly with `422`. **Reproduced only against Postgres, not local SQLite** — the same lesson as F-001.

**Resolution**
All five fixed in golf-web-app (`fix/api-error-contract`). The handicap range (-10 to 54) was also expressed in the schema so it is part of the published contract. The contract suite now passes all six operations. One Schemathesis config choice was made: `positive_data_acceptance` accepts `422`, because input-validation rejections are correct REST behaviour, not defects (`schemathesis.toml`).

**Generalisation**
An OpenAPI spec generated from code is necessary but not sufficient — it documents the *shape* of declared responses, not the *full set* of responses the code actually produces. Contract fuzzing closes that gap. This finding maps to R-006 (now mitigated).

### F-004 — Accessibility sweep found WCAG AA contrast gaps and a missing form label

**Date:** 2026-05-28
**Surfaced by:** First run of the axe-core sweep (`nonfunctional/accessibility/`) over six key pages
**Severity:** Mixed (one critical missing label; serious colour-contrast across the dark theme)

The WCAG 2.1 A/AA sweep passed on home, membership, and course, but flagged three pages with two systemic root causes:

1. **Colour contrast (serious).** Bootstrap's default success `#198754` and danger `#dc3545`, used as text/outline colour on the near-black dark theme, measured 3.86–4.17:1 — under the 4.5:1 AA minimum. Affected outline buttons and `.text-success` links on login, member dashboard, and book-tee-time.
2. **Missing form label (critical).** flatpickr's `altInput: true` generates a visible date input with no accessible name; the original input that carries the `<label for=...>` is hidden. Screen-reader users got an unnamed field on the booking page.

**Resolution**
Both fixed in golf-web-app (`fix/a11y-contrast-and-labels`, PR #7): dark-theme CSS overrides lift the resting success/danger foregrounds above 4.5:1 (hover fills kept dark enough for white text); flatpickr's `onReady` now copies the label text into an `aria-label` on the alt input. The sweep passes all six pages at the serious + critical gate. minor/moderate issues are tracked in the saved axe JSON but do not gate.

**Generalisation**
A component library's defaults are not automatically accessible in a custom theme — Bootstrap's semantic colours assume a light background. And progressive-enhancement widgets (flatpickr) can *remove* accessibility the underlying HTML already had. Both are invisible to functional tests, which is exactly why an automated a11y gate earns its place. Maps to R-008 (now mitigated).

### F-005 — Performance gate caught an N+1 query in the tee-times endpoint

**Date:** 2026-05-28
**Surfaced by:** First CI run of the k6 performance gate (`nonfunctional/performance/`)
**Severity:** Major (latency scales with row count; would worsen as bookings grow)

The k6 gate passed locally but failed in CI: `GET /api/v1/tee-times` p95 was ~653ms against the 500ms budget, while `/api/v1/competitions` sat at 3.85ms. The asymmetry pointed at the endpoint, not the runner. `TeeTimeOut` serializes `slots_remaining` → `booked_count`, which summed the `TeeTime.bookings` relationship; with `lazy='dynamic'` that fired one bookings query per row — ~150 round-trips for a week of slots. A faster local Postgres masked it (174ms); the slower shared CI runner exposed it.

**Resolution**
Fixed in golf-web-app (`fix/api-teetime-nplus1`, PR #8): `TeeTime.bookings` switched to `lazy='selectin'`, batch-loading all bookings for the loaded set in a single query (N+1 → 2). Local p95 fell from ~174ms to ~31ms; the 500ms budget now passes with large margin on CI. `TeeTime.bookings` is only ever summed (never used as a dynamic query), so the change is safe.

**Generalisation**
Two lessons. First, an N+1 is invisible to functional and contract tests — they assert *correctness*, not *cost* — so a performance gate earns its place. Second, perf results are environment-sensitive: a budget that passes on a fast dev machine can fail on a slower shared runner, and that divergence is a feature here — it exposed a real defect rather than hiding it (cf. the SQLite-vs-Postgres lesson in F-001). Maps to R-007 (now mitigated).

### F-006 — Contract fuzzing caught an undocumented 400 on the new AI endpoint

**Date:** 2026-05-29
**Surfaced by:** Schemathesis contract suite, first run against the new `/api/v1/booking-assistant` endpoint
**Severity:** Minor (contract/documentation gap, no crash)

The natural-language booking endpoint (phase 7) shipped with documented responses 200/401/422. On its first contract run, property-based fuzzing sent a request body that was not valid JSON (a raw NUL byte); the API returned 400 Bad Request — Flask rejects a malformed body before the view runs — and that 400 was undocumented, so the spec under-described the endpoint's real behaviour.

**Resolution**
Documented `400 Malformed request body` on the endpoint (golf-web-app PR #10), matching the existing booking endpoint. The contract suite now passes all seven operations.

**Generalisation**
The F-003 lesson held for the new AI feature on day one: an auto-generated spec documents the happy paths the author thought of, not the full set of responses the framework actually produces. The standing contract gate caught the gap automatically the moment the endpoint shipped — no extra effort. Note what contract fuzzing did *not* need to know: that the endpoint is AI-backed is irrelevant at the HTTP boundary; it is asserted like any other service contract. (The model's *semantic* quality is assured separately — see the roadmap's evaluation harness.)

### F-007 — Assistant silently truncated availability to 6 of N matching slots

**Date:** 2026-05-29
**Surfaced by:** Manual exploration of the live AI feature (real Ollama) during phase-7 review
**Severity:** Major (the member cannot see or select the majority of genuinely available slots)

Clicking through the assistant with the real model, an availability request — *"the afternoon of Saturday 30th May for 2 players"* — proposed only 6 slots. `find_candidate_slots` defaulted to `limit=6`, and on the assistant path that capped list **is** the entire visible result set, so 46 of the 52 genuinely bookable afternoon slots were hidden with no indication they existed.

**Resolution**
Fixed in golf-web-app (`fix/assistant-show-all-slots`, PR #11): the default `limit` becomes `None` (return all matching slots, earliest-first); the `limit` param stays for callers that want a shortlist. A unit test asserts the uncapped return.

**Generalisation**
Every automated gate passed — contract, functional and performance assert *correctness* and *cost*, not whether the feature surfaces what the member actually asked for. This was found by a human exploring the live feature, which is exactly why exploratory testing complements the deterministic spine rather than being replaced by it. The cases found here became the seed of the phase-8 golden set (`ai_evaluation/golden_set.yaml`). Maps to R-011.

### F-008 — Assistant silently dropped a time constraint it could not represent

**Date:** 2026-05-29
**Surfaced by:** Manual exploration of the live AI feature (real Ollama)
**Severity:** Major (the member's stated constraint is silently ignored, so wrong slots are proposed)

A request like *"Tuesday morning from 9am"* proposed slots **before** 9am. The root cause was *not* the model: `BookingIntent` could express only a half-day `period`, with no field for a specific time, so "from 9am" was unrepresentable and silently discarded — the model extracted everything the schema allowed.

**Resolution**
Fixed in golf-web-app (`feature/assistant-time-window`, PR #12): added `not_before`/`not_after` (an inclusive time window) to the intent, threaded through the model JSON schema + prompt, the deterministic stub, the matcher, the API schema and the interpretation banner; an exact time ("at 10am") falls out as the degenerate window `[10:00, 10:00]`. A follow-on model quirk — deriving redundant bounds from the bare word "morning" — was tightened in the same PR's prompt.

**Generalisation**
Distinguish a *model* error from a *system* error: the model was not hallucinating; the system could not express the request and, worse, dropped it silently rather than telling the member. The fix was deterministic (schema + matcher), not prompt-tuning. A representable-but-unmet constraint should degrade *transparently* — the UI shows the interpretation so the member can see and correct it. The genuine model errors found alongside this (bare weekdays resolving to the wrong date) are deferred to the phase-8 evaluation harness and recorded in `ai_evaluation/golden_set.yaml`. Maps to R-011.

### F-009 — Functional test flake on the booking-confirm redirect: default Playwright timeout too tight for cold-runner

**Date:** 2026-06-01
**Surfaced by:** Two flake recurrences across consecutive testing-system PRs (#11 and #12), each in the booking-confirm flow
**Severity:** Moderate (no defect; gate eroded by intermittent false-fail)

The functional gate failed once on testing-system PR #11 (`test_member_books_a_tee_time` URL assertion after confirm-click) and once on testing-system PR #12 (`test_assistant_interprets_request_and_books_a_slot` URL assertion after confirm-click). Both passed on rerun without any code change to the SUT or the harness. A single flake is noise; the second recurrence on the same shape — *URL assertion immediately after a navigating click* — made it a signal worth root-causing rather than tolerating.

**Diagnosis**

The SUT booking-confirm flow is a standard Flask form POST → `db.session.commit()` → `flash(...)` → 302 → GET `/member/dashboard` chain. No async, no special timing. Locally the entire chain resolves in well under a second; the SUT is not the variable. The harness side was running Playwright with default options, which set `expect()` assertion timeouts to 5 seconds. `page.click()` does not auto-wait for navigation, so the test's next assertion — `expect(page).to_have_url(re.compile(r"/member/dashboard"))` — fires immediately and polls for at most 5s. On the GitHub-hosted runner, with a cold compose stack and shared CPU/IO, the click → POST → commit → redirect → dashboard-render → URL-change chain can occasionally exceed 5s end-to-end. That is the variance the default timeout has no margin for.

**Resolution**

Two changes in [`fix/r-018-functional-flake`](https://github.com/ayyadam/testing-system/tree/fix/r-018-functional-flake):

1. `functional/conftest.py` calls `expect.set_options(timeout=15_000)` at module load — 15 seconds gives the cold-runner case headroom without masking a genuine regression (a navigation that takes >15s is a defect, not variance).
2. The two known-flaky URL assertions converted from `expect(page).to_have_url(...)` to `page.wait_for_url(...)` (30s default). `wait_for_url` is the Playwright-recommended pattern after a click that triggers navigation — it signals "I am waiting for the next URL" semantically rather than "I am asserting a state I expect to already hold." The remaining `expect.to_have_url` calls in the suite benefit from the 15s timeout via change (1).

**Generalisation**

Two lessons. First, *default tool timeouts are tuned for fast local environments, not slow CI runners*. The same lesson held in F-005 (k6 performance budget — passed locally, failed on the slower CI runner) and F-001 (SQLite vs Postgres permissiveness). A standing assurance habit is now to ask "would this gate's defaults still hold on the slowest environment we run it in?" before shipping it. Second, *a flake is data, not noise*. The single-occurrence flake on PR #11 was easy to wave through with a rerun; the second occurrence on PR #12 made the pattern legible and root-causable. Capturing both was what made the diagnosis possible — had #11's been silently re-run-and-forgotten, the second one would have looked equally isolated.

Maps to R-018 (now mitigated).

### F-010 — Operational endpoint silently leaked into the v1 API contract

**Date:** 2026-06-02
**Surfaced by:** Schemathesis contract gate on testing-system PR #19 (phase 11 observability stack), the same week the regression shipped
**Severity:** Minor (no behavioural defect; the published spec was inaccurate)

Phase 11 added `prometheus-flask-exporter` to the SUT to expose `/metrics` for the observability stack to scrape (golf-web-app PR #13). The exporter registered `/metrics` directly on the Flask app rather than on a blueprint. APIFlask discovers all app-level routes when generating the OpenAPI spec; it added `/metrics` with the default `application/json` content type while the endpoint actually serves `text/plain` (Prometheus exposition format). The first CI run on the matching testing-system phase-11 PR failed at the Schemathesis contract gate — `Received: text/plain; Documented: application/json`.

**Resolution**

Fixed in [golf-web-app PR #14](https://github.com/ayyadam/golf-web-app/pull/14): an APIFlask `spec_processor` in `create_app()` strips `/metrics` from the served spec before publication. The endpoint still exists at runtime (the observability stack scrapes it normally); it just isn't advertised in the v1 JSON API contract. A unit test (`test_metrics_endpoint_not_in_openapi_spec`) fetches `/api/v1/openapi.json` and asserts `/metrics` is absent from `spec['paths']` — any future regression now fails in SUT unit CI before the contract gate has to.

**Generalisation**

Same lesson as F-003: *an auto-generated OpenAPI spec documents the routes the framework discovers, which is not always the set of routes the author considers part of the contract*. F-003 was about the spec under-describing real behaviour (missing 5xx); F-010 is about it over-describing (advertising an operational endpoint as part of the API). Both are the same class of failure — a spec that drifts from author intent because the framework doesn't know what the author meant.

The bigger story is that the standing contract gate caught a regression I introduced in the same PR cycle as the feature that introduced it. The harness did its job: F-003's lesson informed the gate, and the gate then caught the next instance of the same lesson playing out. Maps to R-006.

### F-011 — Repeated runner OOM on Playwright/a11y jobs

**Date:** 2026-06-02 *(third recurrence)*
**Surfaced by:** Post-merge dev push run [`26822385733`](https://github.com/ayyadam/testing-system/actions/runs/26822385733) (Functional Tests, exit 137); also PR #19 second CI (Accessibility, exit 137); also one earlier Functional Tests recurrence.
**Severity:** Minor (each occurrence has passed on rerun) — but recurring, hence promoted to a named finding rather than left as one-off "infra noise".

**Symptom**

Functional Tests (Playwright) or Accessibility (axe) job fails partway through with `Process completed with exit code 137`. Exit 137 = process received `SIGKILL`. No application error, no assertion failure, no test output — the process just disappears. On rerun the same job passes cleanly without any code change.

**Root cause**

The hosted runner is OOM-killing the test process. Playwright launches Chromium per worker, holds it open for the suite, and the cold-start build of the SUT container + Postgres service + Chromium + Python all together brushes the runner's 7 GB memory limit. The hit rate is variable — most runs pass — but it has now been three hits across two job types, which makes it a pattern rather than a one-off.

**Distinction from R-018 / F-009**

F-009 was a *Playwright assertion timeout* — the test was running, the page was navigating, but the assertion's 5s budget ran out before the dashboard URL settled. That's a tight-budget problem in the test code, fixable by `page.wait_for_url(...)`. F-011 is a *runner-level OOM* — the test process is killed by the OS before it can complete or fail. No test-code change would address it. The two findings are in the same neighbourhood (functional layer cold-runner flakiness) but the mechanism is different and so is the response.

**Mitigation**

For now, **rerun-on-hit, do not chase**. The cost calculus: debugging a hosted-runner memory ceiling against a cached image build is a deep rabbit hole; one `gh run rerun --failed` is ten seconds. Mitigation strategies if the rate climbs:
- Reduce Playwright's footprint (single-worker, `--browser=chromium` only, smaller viewports)
- Move to a larger runner class (paid)
- Split the functional layer across multiple smaller jobs

The finding is logged as R-019 and tracked. Re-evaluation trigger: more than ~1-in-10 runs hitting this, or any further job types affected.

**Process gap surfaced alongside this**

This recurrence was reported to me by the user via a GitHub notification, not by me checking. My cadence has been: PR pre-merge checks green → squash-merge → done. I do not currently watch the *post-merge push run* on dev — which executes the merged squash commit and can fail independently of the PR run. Adopting "after merge, also watch the push run on dev" closes the gap.

### F-012 — `confirm.click()` race with the booking page's smooth-scroll animation

**Date:** 2026-06-02
**Surfaced by:** Third post-mitigation recurrence of R-018 on PR #25, this time deep-dived from the failed-run Playwright trace instead of rerun-on-hit.
**Severity:** Major (root cause for R-018's recurring functional flake)

**Symptom**

`test_assistant_interprets_request_and_books_a_slot` (and previously `test_member_books_a_tee_time`) intermittently times out at 30s on `page.wait_for_url(re.compile(r"/member/dashboard"))`. The failed-run screenshot shows the page still on `/member/book-tee-time` with the chosen slot selected — no error message, no navigation. Reruns pass cleanly.

**Root cause** (traced via the failed run's Playwright trace + network log)

The booking page's slot-selection JS does this on click:

```js
function selectTeeTime(id, el) {
    // ...mark slot selected, write hidden input
    const wrapper = document.getElementById('bookingFormWrapper');
    anchorSlot.after(wrapper);              // DOM move
    wrapper.classList.remove('show');       // animation reset
    void wrapper.offsetHeight;              // force reflow
    wrapper.classList.add('show');          // entrance animation
    setTimeout(() => wrapper.scrollIntoView({ behavior: 'smooth' }), 50);
}
```

The 50ms-delayed `behavior: 'smooth'` scroll is the real culprit. Playwright's flow after the slot click:

1. Resolves `#confirmBookingBtn` → finds it.
2. Auto-actionability check: visible, enabled, **stable**. The check observes the bounding box across two animation frames (~16ms apart). On a cold CI runner, this check often completes within the 50ms window *before* the smooth scroll begins, so the box is stable and the check passes.
3. `scrollIntoView` (Playwright's own, instant) — runs.
4. Dispatches the click event.
5. The page's own smooth scroll, queued by the 50ms setTimeout, is now in flight. The click event reaches the button, but the surrounding viewport animation interferes with the click's form-submission side-effect.

Result: the trace shows `performing click action → click action done → navigations have finished` (with no navigation actually scheduled). The form never POSTs. The test then waits the full 30s `wait_for_url` budget for a URL that never gets visited.

This is the **same R-018 family** as F-009, but the mechanism is one layer deeper than the original diagnosis. F-009 named "cold-runner spike on the POST → 302 → dashboard GET chain" and fixed it with longer assertion timeouts + `wait_for_url`. That mitigation reduced hit rate but did not address the underlying race because the underlying race is **not server-side latency** — it's a client-side animation race that prevents the POST from happening at all.

**Mitigation** (this PR)

`functional/conftest.py` overrides pytest-playwright's `page` fixture to register an init script that sets `document.documentElement.style.scrollBehavior = 'auto'` on every navigation. CSS smooth-scroll is bypassed for tests; Playwright's deterministic scroll is the only one in play. The fixture composes naturally with `member_page` (which is built on `page`) so every functional test gets the deterministic behaviour for free.

Tests still exercise the real submit button, the real form, the real handler — only the cosmetic transition is bypassed. The application's smooth-scroll UX is unchanged.

**Local validation:** 5/5 pass on the previously-flaky tests after the fix.

**Generalisation**

Two-step deepening of R-018 across three PRs makes the methodological point: *rerun-on-hit is a tactic, not a strategy*. The cheapest fix the second and third time was "rerun again", and we did that. The right fix was diagnostic — pull the trace, find the actual mechanism, kill the race. Each rerun-on-hit deferred this work and let the same race keep showing up; the right time to do the diagnostic was the moment R-018 hit twice past its first mitigation. Adopted habit: *the second mitigation-pass recurrence of any flake gets a deep-dive PR*, not another rerun.

R-018 status moves from *mitigated* (pre-F-012) to **closed** (post-F-012) in the register if this fix holds for the next 5–10 functional CI runs. Until then it stays *mitigated* with F-012 linked.

## 12. Roadmap

The full phased plan lives in conversational notes; the abbreviated public form:

| Phase | Goal | Status |
|---|---|---|
| 0 | testing-system skeleton (uv, pytest, ruff, CI) | **Done** |
| 1 | Test strategy + risk register | **Done** |
| 2 | golf-web-app JSON API + OpenAPI spec | **Done** |
| 3 | Playwright user journeys (functional) | **Done** |
| 4 | Schemathesis contract tests | **Done** |
| 5a | Accessibility (axe) sweep + gate in CI | **Done** |
| 5b | Performance (k6) budgets in CI | **Done** |
| 6 | Data quality (pandera) on the live database | **Done** |
| 7 | golf-web-app AI feature (natural-language booking, local Ollama) | **Done** |
| 8 | AI evaluation harness | **Done (v1)** — deterministic + LLM-judge (holistic + fuzzy) |
| 9 | Risk-prioritisation agent (PR diff → ranked test plan) | **Done (v2 v2)** — v2 v1 added deterministic `covered_by` + `is_gap` and a relevance scale; v2 v2 added a golden-set evaluation tier with deterministic scoring (precision/recall/F1). Baseline F1 0.526 across 4 cases — measurable now. PR-comment Action deferred (needs hosted-LLM commitment) |
| 10 | Triage agent (CI failure clustering) | **Done (v1 v2)** — v1 v1: heuristic clustering + LLM category + R-ID xref. v1 v2: golden-set eval tier with deterministic scorer. 5/5 baseline on five real failures from last 30 days |
| 11 | Prometheus + Grafana observability stack | **Done (v1)** — local stack scraping the SUT, provisioned dashboard with SLOs aligned to the k6 gate; closes R-013. Loki + Alertmanager deferred to v2 |
| 12 | Exploratory testing agent + tests of agents | **Done (v1 v1, v1 v2, v2 v1, v2 v2)** — see sub-roadmap below for deferred-but-tracked work |

### Phase 12 sub-roadmap

The exploratory testing arc has its own sub-roadmap because the agentic surface has more dimensions than the deterministic spine. Tracked here so deferred items don't drift across PR descriptions and READMEs.

| Sub-phase | Goal | Status |
|---|---|---|
| v1 v1 | Exploratory agent — **API surface**: OpenAPI-driven, LLM payload variants per endpoint, LLM-judged responses | **Done** ([`explore_agent/reports/report.md`](../explore_agent/reports/report.md)) |
| v1 v2 | Exploratory agent — **UI surface**: Playwright tours, LLM plan + LLM judgement per step | **Done** ([`explore_agent/reports/ui/report.md`](../explore_agent/reports/ui/report.md)) |
| v2 v1 | **Golden-set eval tier** for the explore agent — mirrors [`risk_agent.eval`](../risk_agent/eval.py) and [`triage_agent.eval`](../triage_agent/eval.py) (deterministic scorer, no LLM in scoring) | **Done** — baseline 50.0% accuracy (9/18); [`explore_agent/reports/eval-report.md`](../explore_agent/reports/eval-report.md) |
| v2 v2 | **Adversarial regression tests on existing agents** — run `risk_agent` / `triage_agent` N times against fixed inputs, assert invariants hold across LLM jitter | **Done** — 12/12 schema-valid, 12/12 closed-vocab, 100% top-result stability; [`tests/agents/reports/regression-report.md`](../tests/agents/reports/regression-report.md) |

Phase 9 v3 (queued — fix surfaced by phase 12 v2 v2):

- **Phase 9 v3 — `risk_agent` prompt + register-framing fix**. The v2 v2 regression run surfaced a stable-divergent case on PR #12: the agent emits R-002 (concurrent bookings) at relevance 3 on a read-side PR that doesn't touch the booking write path. A model-swap experiment confirmed it's not capability-bound (qwen2.5:32b and qwen2.5:14b produce near-identical R-002 rationales). The fix lives in two places: (a) tighten the system prompt with a subject-vs-adjacent discrimination rule, and (b) sharpen R-002's register row from "concurrent bookings of the same tee slot...cause overbooking" to scope it explicitly to the booking *creation* endpoint. Phase 9 v3 lands those changes, re-baselines the v2 v1 eval (F1 should move from 0.526), and re-runs v2 v2 to confirm the warning quiets.

Beyond v2, deferred-but-tracked work:

- **Adaptive single-step exploration mode** *(architectural fix to plan-once-from-starting-page)*. The current UI agent commits to a multi-step plan based only on the starting page's interactive elements; selectors on pages the planner hasn't seen yet are hallucinated. The booking-assistant tour's first run made this visible — the planner waited for `.candidate-slot` (invented) while the actual class is `.booking-slot`. The architectural fix is to drop the upfront plan and have the LLM decide one next action per step from the current page state — the difference between a *plan* and a *policy*. **Decision pattern:** the v2 v1 eval will quantify how often hallucination produces a dead-end versus a real finding; the eval result determines whether this jumps the queue or stays here. Same evidence-led pattern as R-011's deployed-model decision becoming numbers-led after phase 8.
- **Free-form UI exploration mode** — the LLM picks goals from a surface map of the SUT instead of running fixed tours.
- **State-mutating tours** — booking confirmation, admin flows, visitor registration. Held out of v1 because the SUT state would drift across runs and the report would not be reproducible.
- **Cross-tour memory** — each tour currently starts fresh. A finding from one tour could in principle inform the next tour's plan or goal selection.
- **Auth-bypass probing on the API surface** — probes without credentials, with wrong credentials, or with another member's token to verify the auth boundary holds. Surfaced in v1 v1's scope notes; deferred because in-scope probing already exercises every endpoint with a valid token.

## Appendix A: Glossary

- **SUT** — system under test. Here: `golf-web-app`.
- **Harness** — assurance code that targets the SUT. Here: `testing-system`.
- **Service boundary** — an interface where one component's responsibility ends and another's begins. We assert at boundaries because that's where contracts live.
- **LLM-judge** — an LLM prompted to score another model's output against a rubric. Used in `ai_evaluation/` where deterministic asserts don't fit.
- **Golden set** — a curated input/expected-output dataset used to evaluate models against a known baseline.
