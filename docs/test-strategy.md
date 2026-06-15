# Test Strategy — golf-web-app

**Status:** living document — updated as the assurance harness matures.
**Owner:** Adam
**Last updated:** 2026-06-15 *(F-037 / B4 v1 — resilience/chaos pillar: 1/2 scenarios pass — DB-outage degrades gracefully but does NOT fail fast (`/course` hangs, no DB statement timeout), process-death auto-recovers via the restart policy (RestartCount-proven). One representative fault per failure axis; grey-failure (toxiproxy) axis is v2. Next net-new pillars B5/B11)*

---

## 1. Purpose

This document describes how we assure the quality of [golf-web-app](https://github.com/ayyadam/golf-web-app) — the system under test — using the [assurance-harness](https://github.com/ayyadam/assurance-harness) harness. It exists to:

- Make our assurance approach explicit so delivery decisions can be informed by it
- Give a reviewer of this work a clear picture of *judgement*, not just tooling
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
| Contract | **Done** | Schemathesis vs OpenAPI | `assurance-harness/contract/` | Verify the JSON API conforms to its spec under property-based inputs |
| UI / E2E journeys | **Done** | Playwright + pytest | `assurance-harness/functional/` | Exercise the booking journey, the natural-language booking assistant, and access-control boundaries in a real browser, as a member experiences them |
| Accessibility | **Done** | axe-core (axe-playwright-python) | `assurance-harness/nonfunctional/accessibility/` | WCAG 2.1 A/AA sweep of key pages; gate the PR on serious + critical violations, track the rest |
| Performance | **Done** | k6 (thresholds-as-code) | `assurance-harness/nonfunctional/performance/` | Latency/error budgets on the read-path API; fail the PR on regression beyond budget |
| Security | **Done (B1)** | Bandit + CodeQL (SAST), pip-audit (SCA), gitleaks (secrets), OWASP ZAP baseline (DAST) | `assurance-harness/nonfunctional/security/` | Shift-left security gate: dependency CVEs (gate any non-allowlisted), secret scanning (hard gate), static analysis + a DAST baseline (advisory, ratchet). The agentic crown — [`security_agent`](../security_agent/README.md) (B1c) — judges these findings (FP-vs-real + disposition + R-ID). See [F-029](#f-029--b1-security-gate-shift-left-sast-sca-secrets-and-dast), [F-030](#f-030--b1c-security_agent-judges-the-b1-findings-verdict-disposition-r-id-77-baseline) |
| Data quality | **Done** | pandera (schemas + invariants) | `assurance-harness/data_quality/` | Validate the live database against column contracts and business-rule invariants (e.g. 18 holes with a 1..18 stroke-index permutation) |
| AI evaluation | **Done (phase 8 v1)** | Black-box golden-set scoring (deterministic + LLM-judge) | [`assurance-harness/ai_evaluation/`](../ai_evaluation/README.md) | Quantifies model accuracy, safety, latency across a model list. Two grading tiers — deterministic field equality + an LLM-judge (holistic 0-10 + per-rubric fuzzy pass/fail). Current 5-model report: [`ai_evaluation/reports/report.md`](../ai_evaluation/reports/report.md) |
| Risk-prioritisation (advisory) | **Done (phase 13 v3)** | Local Ollama agent + deterministic register pre-filter (path + content) + deterministic post-processing + golden-set eval | [`assurance-harness/risk_agent/`](../risk_agent/README.md) | Given a PR diff + the live risk register, produces a ranked test plan with `covered_by` per risk, coverage-gap flags, relevance label (`direct` / `plausible`), and exploratory probes. Advisory only, not a CI gate. Phase 9 v2 v1 → v4 v2: prompt + row tuning iterations (F1 0.526 → 0.462 across the 9-case set). Phase 13: deterministic register pre-filter — v1 path-based filtering (F1 → 0.710); v2 mapping tightening (F1 → 0.733); **v3 content-aware filtering** for R-007, R-009, R-010, R-012, R-019 + R-002 path narrowing + comment-line stripping in marker matching. **F1: 0.733 → 0.929** (precision 0.688 → 0.929, recall 0.786 → 0.929; **7 of 9 cases at F1 1.000**). Single FP and single FN remaining are both honest LLM-calibration calls. F-017's cross-row coupling hypothesis confirmed via a side-effect of v3's R-007 filter. Phase 13 closed. See [F-013](#f-013--risk_agent-subject-vs-adjacent-rule--sharpened-rows-lift-f1-0526--0588), [F-014](#f-014--golden-set-growth-4--9-cases-surfaces-three-new-failure-modes-honest-baseline-f1-0421), [F-015](#f-015--r-006-row-sharpening-lifts-f1-0421--0462-three-attempted-sharpenings-reveal-the-llm-tuning-ceiling), [F-016](#f-016--deterministic-register-pre-filter-phase-13-v1-lifts-f1-0462--0710), [F-017](#f-017--mapping-tightening-phase-13-v2-lifts-f1-0710--0733-cross-row-coupling-surfaced), [F-018](#f-018--content-aware-filtering-phase-13-v3-lifts-f1-0733--0929-phase-13-closed), and [`risk_agent/reports/eval-report.md`](../risk_agent/reports/eval-report.md) |
| Triage (advisory) | **Done (phase 10 v1 v2)** | Local Ollama agent over `gh` log dumps + golden-set eval | [`assurance-harness/triage_agent/`](../triage_agent/README.md) | Clusters failed CI runs by signature `(test path, test name, error class)`, then asks the LLM for a category (flake / defect / infra / env) and a candidate register R-ID per cluster. Closed-vocabulary enum on the R-ID — the model cannot invent risks. v1 v2 added a golden-set evaluation tier ([`triage_agent.eval`](../triage_agent/eval.py)) scoring the agent against expected (category, R-ID) per known cluster — deterministic, no LLM in scoring. Current baseline: 5/5 on category, R-ID, and combined. Historical insight from v1 v1: R-018 was actually present at run #18 (2026-05-28), three weeks before it was logged. See [`triage_agent/reports/report.md`](../triage_agent/reports/report.md) and [`triage_agent/reports/eval-report.md`](../triage_agent/reports/eval-report.md) |
| Production observability | **Done (phase 11 v1)** | Prometheus + Grafana (metrics only; Loki + Alertmanager v2 candidates) | [`assurance-harness/observability/`](../observability/README.md) | Local stack scraping the SUT's `/metrics` (provisioned by `prometheus-flask-exporter`), provisioned dashboard with request rate / error rate / p95 latency / per-path breakdowns. SLO thresholds on the dashboard match the k6 perf gate's pre-merge budget — same SLOs, two enforcement points. Closes R-013. See [`observability/README.md`](../observability/README.md) and [`observability/evidence/grafana-sut-overview.png`](../observability/evidence/grafana-sut-overview.png) |
| Exploratory (advisory) | **Done (phase 12 v2 v1 + deferred-E + F-020 / F-021 sharpening)** | Local Ollama agent — API surface via OpenAPI, UI surface via Playwright, deterministic eval tier, spec-aware auth-bypass probing | [`assurance-harness/explore_agent/`](../explore_agent/README.md) | Two surfaces share the same package and the same closed-enum + LLM-jury pattern. **API** (`explore_agent.run`, v1 v1): every v1 endpoint probed with three LLM-generated payload variants (happy / edge / abusive, including prompt-injection on AI endpoints), responses classified into `expected` / `unexpected_5xx` / `schema_drift` / `business_rule_concern` / `auth_boundary_concern` / `documented_public_endpoint`. Phase 12 **deferred-E** added a credential-mode axis: each endpoint's happy payload is re-sent under `unauth` (no token), `wrong_creds` (invalid bearer), and `other_member` (a different seeded member's valid token). The first two are judged mechanically — **spec-aware** since F-020: a 2xx on `unauth`/`wrong_creds` is `auth_boundary_concern` only when the OpenAPI spec marks the endpoint as auth-required (spec/impl drift); a 2xx where the spec documents the endpoint as public is `documented_public_endpoint` (informational, for reviewer confirmation of design intent). `other_member` remains LLM-judged with auth-mode context — **prompt-tightened in F-021** (phase A N=3 stable-divergent measurement → phase B caller-as-source-of-truth framing + concrete shared/identity/owner-scoped examples + explicit exclusions → phase C N=3 verification: 5 stable false-positives → 0). **UI** (`explore_agent.ui_run`, v1 v2): three predefined tours, each with an LLM-planned step sequence executed in Playwright, per-step state captured and LLM-judged into `expected` / `unexpected_5xx` / `js_error` / `dead_end` / `business_rule_concern`. **Eval** (`explore_agent.eval`, v2 v1): golden-set evaluation tier mirroring [`risk_agent.eval`](../risk_agent/eval.py) and [`triage_agent.eval`](../triage_agent/eval.py) — deterministic scoring against expected category per (endpoint, variant), no LLM in the scoring path. **Baseline (phase 12 v2 v1, 2026-06-02): 50.0% accuracy (9/18 cases)** — every case's expected category is `expected` (no defects in the seeded surface) and the agent over-flagged 9 of them (7 as `business_rule_concern`, 2 as `unexpected_5xx`). **F-022 re-baseline (2026-06-05, post-F-021): 64.8% mean across N=3** (range 0.611–0.667; 11 stably correct, 6 stably wrong, 1 jitter case). The three formerly-wrong cases that flipped to `expected` are `competitions-get-abusive` (was `unexpected_5xx`) and `tee-times-list-edge` + `tee-times-list-abusive` (were `business_rule_concern`). The 6 stable-wrong cases are all `edge` and `abusive` variants on write or complex endpoints (`tee-times-detail`, `booking-assistant`, `bookings-create`). **F-023 reframe (2026-06-05): 100.0% across N=3** (18/18 each run, perfectly stable) — `business_rule_concern` recast as *wrongful acceptance* (the API accepted something it should have refused, body proves it) so 4xx refusals and gracefully-handled weird input are `expected`; non-blinding proven by a positive-control probe (a synthetic past-date 201 still fires `business_rule_concern` high). This quantifies the v1 v1 over-flagging behaviour and gives a measurable target for any future judge-prompt tightening or model swap. v1 v2's UI agent also surfaced the *plan-once-from-starting-page* limitation cleanly (LLM hallucinated `.candidate-slot` when the actual class was `.booking-slot`); the architectural fix (adaptive single-step) is tracked in the [phase-12 sub-roadmap](#phase-12-sub-roadmap), with the eval baseline as its decision input. Both probing surfaces remain local-only (cost-prohibitive for CI); the eval is also local-only. See [F-019](#f-019--auth-bypass-probing-phase-12-deferred-e-surfaces-three-get-endpoints-accepting-anonymous-traffic), [`explore_agent/reports/report.md`](../explore_agent/reports/report.md) (API), [`explore_agent/reports/ui/report.md`](../explore_agent/reports/ui/report.md) (UI), [`explore_agent/reports/eval-report.md`](../explore_agent/reports/eval-report.md) (eval). |
| Security triage (advisory) | **Done (B1c)** | Local Ollama agent over the B1 scanner findings + golden-set eval | [`assurance-harness/security_agent/`](../security_agent/README.md) | The agentic-layer interpreter over [`nonfunctional/security/`](../nonfunctional/security/): the scanners detect, this agent judges. Per finding — **SARIF-native** since F-033: SAST (Bandit), SCA (raw pip-audit), secrets (gitleaks, values redacted), and any SARIF source via `--sarif` (e.g. CodeQL) — it emits a **verdict** (`true_positive` / `false_positive` / `expected_by_design`), a **disposition** (`remediate` / `allowlist` / `accept`), a **candidate register R-ID** (closed-vocabulary enum — the model can only pick a real risk or `null`), and a grounded rationale. It re-derives the manual B1 triage (F-029) automatically: it runs pip-audit **raw** (no allowlist) so it can re-judge the very CVEs the gate suppresses. Mirrors `triage_agent` — heuristic normalise/dedupe spine, LLM judgement, deterministic golden-set scorer. **Baseline (B1c v1, 7 findings): 1.000 on verdict, disposition, R-ID, and combined (7/7)** — the 3 Bandit hits correctly called scanner noise (the `TOKEN_SALT` salt, the `'Bearer'` scheme word, the container `0.0.0.0` bind), the 4 dependency CVEs correctly routed to accept-and-track against R-020. **After F-032** (R-020 remediated) the four SCA cases retired from the live golden set — active baseline now **3/3 on the SAST surface**, the 7/7 preserved here + in git. Caveat: a small, clean-cut set — SCA verdicts are nearly free, and the value is the disposition + R-ID, not the verdict. **Write-back (F-031):** [`writeback.py`](../security_agent/writeback.py) reconciles the agent's `allowlist` judgement against the live `sca_allowlist.txt` and proposes a diff (add / remove-stale / conflict / in-sync), propose-by-default with `--apply` — closing the detect→judge→reconcile loop. **SARIF-native (F-033):** a generic SARIF normaliser folds in gitleaks (secrets, redacted, path-based judgement) and makes CodeQL ingestible via `--sarif`; proven by a hermetic positive control (the live secret surface is clean). Local-only. See [F-030](#f-030--b1c-security_agent-judges-the-b1-findings-verdict-disposition-r-id-77-baseline), [F-031](#f-031--security_agent-write-back-reconcile-the-judgement-against-the-live-sca-allowlist), [F-033](#f-033--security_agent-goes-sarif-native-gitleaks-secrets-folded-in-proven-by-a-positive-control), [`security_agent/reports/report.md`](../security_agent/reports/report.md), [`security_agent/reports/eval-report.md`](../security_agent/reports/eval-report.md) |
| Tests of the harness itself | **Done (phase 12 v2 v2 + F-024)** | pytest (LLM-gated via `RUN_AGENT_REGRESSION=1`) | [`assurance-harness/tests/agents/`](../tests/agents/README.md) | Adversarial regression suite for `risk_agent` and `triage_agent`: each agent invoked N=3 times against cached fixtures, with hard invariants (schema validity, closed-vocabulary on every emitted R-ID, relevance in {2, 3}), soft invariants (top-result stability ≥ 0.66 across runs), and a **stable-divergent warning** (test still passes, but emits a `StableDivergentWarning` and flags the case in the rendered report when the agent's stable answer disagrees with the golden set's expected top-1). The eval tiers measure *accuracy*; this measures *stability under LLM jitter* and surfaces stable-but-wrong cases that single-run eval averages can hide. v2 v2's baseline run surfaced one stable-divergent case (`risk_agent` PR #12 — R-002 stably top, golden expected R-011); phase 9 v3 fixed it via subject-vs-adjacent prompt + sharpened register rows (see [F-013](#f-013--risk_agent-subject-vs-adjacent-rule--sharpened-rows-lift-f1-0526--0588)). Current run: 12/12 schema-valid, 12/12 closed-vocab, 100% top-result stability across all 4 cases, **no stable-divergent warnings**. **F-024** adds a third agent under test — the `explore_agent` judge — with a *non-blinding positive control*: a synthetic wrongful-acceptance probe (a past-date booking the API wrongly accepted with 201) run N=3 through the live judge, asserting it still fires `business_rule_concern` (jitter-tolerant mode + ≥ 0.66 stability floor). This is the recall sentinel the all-`expected` explore eval structurally cannot be — together they bracket the judge: the eval catches over-flagging regressions, this test catches blinding regressions. Local-only — LLM calls would flake CI. See [`tests/agents/reports/regression-report.md`](../tests/agents/reports/regression-report.md) and [F-024](#f-024--non-blinding-positive-control-made-durable-the-eval-measures-precision-this-test-guards-recall) |

A traditional test pyramid does not map cleanly onto this project because the SUT is one of several concerns alongside data quality, AI evaluation, and observability. The above is a *responsibility map*, not a pyramid.

## 6. Tooling

| Tool | Purpose | Adopted? |
|---|---|---|
| Python 3.12 | Language runtime for both SUT and harness | Yes |
| `uv` | Dependency and venv management for assurance-harness | Yes |
| pip + venv | Dependency management for golf-web-app (pre-existing) | Yes |
| pytest | Test runner everywhere | Yes |
| ruff | Lint + format for assurance-harness | Yes |
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

**`assurance-harness/.github/workflows/assurance.yml`** — runs the harness. Triggers on push and PR to `master` and `dev`.
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
**Surfaced by:** Two flake recurrences across consecutive assurance-harness PRs (#11 and #12), each in the booking-confirm flow
**Severity:** Moderate (no defect; gate eroded by intermittent false-fail)

The functional gate failed once on assurance-harness PR #11 (`test_member_books_a_tee_time` URL assertion after confirm-click) and once on assurance-harness PR #12 (`test_assistant_interprets_request_and_books_a_slot` URL assertion after confirm-click). Both passed on rerun without any code change to the SUT or the harness. A single flake is noise; the second recurrence on the same shape — *URL assertion immediately after a navigating click* — made it a signal worth root-causing rather than tolerating.

**Diagnosis**

The SUT booking-confirm flow is a standard Flask form POST → `db.session.commit()` → `flash(...)` → 302 → GET `/member/dashboard` chain. No async, no special timing. Locally the entire chain resolves in well under a second; the SUT is not the variable. The harness side was running Playwright with default options, which set `expect()` assertion timeouts to 5 seconds. `page.click()` does not auto-wait for navigation, so the test's next assertion — `expect(page).to_have_url(re.compile(r"/member/dashboard"))` — fires immediately and polls for at most 5s. On the GitHub-hosted runner, with a cold compose stack and shared CPU/IO, the click → POST → commit → redirect → dashboard-render → URL-change chain can occasionally exceed 5s end-to-end. That is the variance the default timeout has no margin for.

**Resolution**

Two changes in [`fix/r-018-functional-flake`](https://github.com/ayyadam/assurance-harness/tree/fix/r-018-functional-flake):

1. `functional/conftest.py` calls `expect.set_options(timeout=15_000)` at module load — 15 seconds gives the cold-runner case headroom without masking a genuine regression (a navigation that takes >15s is a defect, not variance).
2. The two known-flaky URL assertions converted from `expect(page).to_have_url(...)` to `page.wait_for_url(...)` (30s default). `wait_for_url` is the Playwright-recommended pattern after a click that triggers navigation — it signals "I am waiting for the next URL" semantically rather than "I am asserting a state I expect to already hold." The remaining `expect.to_have_url` calls in the suite benefit from the 15s timeout via change (1).

**Generalisation**

Two lessons. First, *default tool timeouts are tuned for fast local environments, not slow CI runners*. The same lesson held in F-005 (k6 performance budget — passed locally, failed on the slower CI runner) and F-001 (SQLite vs Postgres permissiveness). A standing assurance habit is now to ask "would this gate's defaults still hold on the slowest environment we run it in?" before shipping it. Second, *a flake is data, not noise*. The single-occurrence flake on PR #11 was easy to wave through with a rerun; the second occurrence on PR #12 made the pattern legible and root-causable. Capturing both was what made the diagnosis possible — had #11's been silently re-run-and-forgotten, the second one would have looked equally isolated.

Maps to R-018 (now mitigated).

### F-010 — Operational endpoint silently leaked into the v1 API contract

**Date:** 2026-06-02
**Surfaced by:** Schemathesis contract gate on assurance-harness PR #19 (phase 11 observability stack), the same week the regression shipped
**Severity:** Minor (no behavioural defect; the published spec was inaccurate)

Phase 11 added `prometheus-flask-exporter` to the SUT to expose `/metrics` for the observability stack to scrape (golf-web-app PR #13). The exporter registered `/metrics` directly on the Flask app rather than on a blueprint. APIFlask discovers all app-level routes when generating the OpenAPI spec; it added `/metrics` with the default `application/json` content type while the endpoint actually serves `text/plain` (Prometheus exposition format). The first CI run on the matching assurance-harness phase-11 PR failed at the Schemathesis contract gate — `Received: text/plain; Documented: application/json`.

**Resolution**

Fixed in [golf-web-app PR #14](https://github.com/ayyadam/golf-web-app/pull/14): an APIFlask `spec_processor` in `create_app()` strips `/metrics` from the served spec before publication. The endpoint still exists at runtime (the observability stack scrapes it normally); it just isn't advertised in the v1 JSON API contract. A unit test (`test_metrics_endpoint_not_in_openapi_spec`) fetches `/api/v1/openapi.json` and asserts `/metrics` is absent from `spec['paths']` — any future regression now fails in SUT unit CI before the contract gate has to.

**Generalisation**

Same lesson as F-003: *an auto-generated OpenAPI spec documents the routes the framework discovers, which is not always the set of routes the author considers part of the contract*. F-003 was about the spec under-describing real behaviour (missing 5xx); F-010 is about it over-describing (advertising an operational endpoint as part of the API). Both are the same class of failure — a spec that drifts from author intent because the framework doesn't know what the author meant.

The bigger story is that the standing contract gate caught a regression I introduced in the same PR cycle as the feature that introduced it. The harness did its job: F-003's lesson informed the gate, and the gate then caught the next instance of the same lesson playing out. Maps to R-006.

### F-011 — Repeated runner OOM on Playwright/a11y jobs

**Date:** 2026-06-02 *(third recurrence)*
**Surfaced by:** Post-merge dev push run [`26822385733`](https://github.com/ayyadam/assurance-harness/actions/runs/26822385733) (Functional Tests, exit 137); also PR #19 second CI (Accessibility, exit 137); also one earlier Functional Tests recurrence.
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

R-018 status moves from *mitigated* (pre-F-012) to **closed** (post-F-012) in the register if this fix holds for the next 5–10 functional CI runs. **Update (2026-06-03):** 5 consecutive clean Functional Tests runs (PR #26's post-merge run, PR #27's CI + post-merge, PR #28's CI + post-merge, PR #29's CI + post-merge, PR #30's CI + post-merge) have validated F-012 without recurrence. R-018 status is now **closed** in the register, and F-009's 15s `expect.set_options(timeout=15_000)` has been reverted to Playwright's 5s default — the timeout bump was a wrong-problem mitigation that F-012 made unnecessary.

### F-013 — `risk_agent` subject-vs-adjacent rule + sharpened rows lift F1 0.526 → 0.588

**Date:** 2026-06-02
**Surfaced by:** Phase 12 v2 v2's stable-divergent warning on PR #12 — `risk_agent` ranked R-002 (concurrent bookings) top across all 3 runs, but the golden set expected R-011 (AI booking correctness). A model-swap experiment (qwen2.5:32b → qwen2.5:14b) reproduced the over-pull with near-identical R-002 rationale, ruling out model capability and pointing at prompt or register framing.
**Severity:** Moderate (regression-suite divergent signal; eval false-positive contributor)

**Diagnosis**

The v1 / v2 v1 system prompt's relevance scale gave the agent only one principle for "is this risk raised by this diff?" — keyword and surface proximity. PR #12 changed natural-language time-of-day parsing in the booking assistant. R-002's row mentioned "tee slot", "booking", "overbooking"; the agent matched on shared terminology and emitted R-002 at relevance 3 alongside the (correct) R-011. The eval treated R-002 as a false positive; the v2 v2 regression flagged the case as stable-divergent.

The same pattern was visible across other cases:

- PR #7 (a11y CSS): R-018 ("functional tests flake on navigation-after-click") emitted at 2 — adjacent surface (test layer), not subject.
- PR #11 (F-007 slot listing): R-012 ("prompt injection in AI booking inputs") emitted at 3 — adjacent feature, not subject.

**Fix** (this PR)

Two complementary changes:

1. **System prompt** — added an explicit "subject vs adjacent" rule after the relevance scale:

   > A risk is raised by a diff when the diff modifies the SUBJECT MECHANISM the risk row names, not merely shared terminology or surface. […] Worked example: a diff improving how the booking assistant interprets time-of-day constraints raises R-011 (AI feature correctness — the assistant IS the subject mechanism) but does NOT raise R-002 (concurrent overbooking — the transaction boundary at POST /book is untouched).

2. **Risk-register rows** — sharpened R-002, R-018, and R-019 to name their subject mechanisms explicitly, not just keyword surfaces:

   - **R-002:** scoped to "the booking-creation request's race against the uniqueness check at the POST /book transaction boundary — not slot listing, availability filtering, AI intent parsing, or other booking-adjacent surface".
   - **R-018:** scoped to "the Playwright/functional layer's interaction with post-click client-side behaviour — not unrelated application code, server-side endpoints, CSS-only changes, or AI-intent parsing".
   - **R-019:** scoped to "the hosted-runner memory boundary — raised by changes that add browser contexts, parallelise page navigations, or expand axe-core sweep scope. Application-code changes that don't materially increase test-side memory pressure do NOT raise this risk".

The system-prompt rule alone is necessary but not sufficient — it teaches the agent *how to read* a row, but the row itself has to *contain* a subject mechanism. The first refresh (prompt change + R-002 only) kept F1 at 0.526: R-002 dropped from PR #12, but R-018 and R-019 over-pulls increased to replace it. Sharpening R-018 and R-019 closed the loop.

**Measurement**

| Metric | Before v3 | After v3 prompt + R-002 only | After v3 (full) |
|---|---|---|---|
| F1 | 0.526 | 0.526 | **0.588** |
| Precision | 0.417 | 0.417 | **0.500** |
| Recall | 0.714 | 0.714 | 0.714 |
| Relevance accuracy | 0.800 | 0.600 | **0.800** |
| FP count | 7 | 7 | **5** |
| PR #12 top R-ID (stable across 3 runs) | R-002 ✗ | R-011 ✓ | R-011 ✓ |
| v2 v2 stable-divergent warnings | 1 | 0 | 0 |

The named target (PR #12's stable-divergent case) was hit by the prompt + R-002 change alone; the F1 lift required also sharpening R-018 and R-019 because the prompt change exposed those as the next layer of keyword-broad rows.

**Generalisation**

The result names a pattern worth keeping: **a system-prompt rule and the artifact it operates on are co-designed**. Asking the agent to "match subject mechanisms" only works if the register rows *contain* subject mechanisms. The first half of the fix (prompt only) reshuffled the error rather than reducing it — that's the diagnostic signal that the artifact also needs work. The same pattern likely applies to triage_agent (categories/clusters), the explore_agent (probe judge prompts vs endpoint specs), and to LLM-as-judge tiers in general.

R-002 stays *open* (the underlying overbooking risk is still un-mitigated by an automated check); the register-row change is about *how the risk is described*, not whether it exists. The mitigation column still names the planned Schemathesis concurrency probe.

### F-014 — Golden-set growth 4 → 9 cases surfaces three new failure modes; honest baseline F1 0.421

**Date:** 2026-06-03
**Surfaced by:** Phase 9 v4 v1 — adding 5 new golden-set cases (PRs #2, #3, #5, #6, #14) across varied diff shapes (CI workflow, server-side refactor, API error contract, security input handling, OpenAPI spec drift) deliberately chosen to stress-test v3 outside the original 4 cases.
**Severity:** Moderate (the *measurement* of agent quality was overfitted; the agent's *behaviour* hasn't regressed — it's the same agent, more honestly scored)

**Finding**

| Metric | v3 final (4 cases) | v4 v1 baseline (9 cases) |
|---|---|---|
| F1 | 0.588 | **0.421** |
| Precision | 0.500 | 0.333 |
| Recall | 0.714 | 0.571 |
| Relevance accuracy | 0.800 | 0.875 |
| TPs / FPs / FNs | 5 / 5 / 2 | 8 / 16 / 6 |

The headline F1 dropped. That is the *point* of v4 v1: the 4-case set was not representative, and any v3 (or earlier) claim about agent quality is tied to that set, not to "the agent's behaviour on golf-web-app PRs in general". The new baseline is honest.

**Three failure modes the bigger set exposed:**

1. **The v3 subject-mechanism rule on R-002 does not fire on PR #3** (the deliberate stress test). PR #3 refactors the booking-create flow from inline route handlers into a service layer. The check-then-create pattern *at the POST /book transaction boundary* is preserved verbatim and relocated. R-002's row was sharpened in v3 precisely to name this boundary. The agent did not pull R-002 — it emitted R-012, R-013, R-014, R-015 instead. The PR #3 F1 is **0.000**. The v3 rule taught the agent to recognise the subject mechanism on PRs that *change inputs* to that mechanism (the AI-parsing case the prompt's worked example covers); it does not appear to generalise to PRs that *relocate* the same mechanism without changing inputs. The prompt or the row needs a second pass.

2. **R-006 has its own keyword-broad-row problem.** PR #6 (null-byte rejection) and PR #14 (hide /metrics from OpenAPI spec) both materially change the API contract. The agent missed R-006 on both — F1 0.400 and 0.000 respectively. On PR #6 the agent saw the diff as security input handling (and correctly pulled R-003 at plausible); on PR #14 it saw the diff as observability cleanup (and incorrectly pulled R-013 instead). R-006's row currently reads "no service-boundary contract verification" — that describes *what was missing* (a gap that has since been mitigated), not the subject mechanism *the contract surface itself*. The same v3 pattern that fixed R-002 applies here.

3. **Pattern continues: R-012, R-013, R-015 are still over-pulled on adjacent surfaces.** R-012 (prompt injection) on PRs #5 and #6 (no AI surface). R-015 (PII in fixtures) on PRs #5 and #6 (the "test data" surface match). R-013 (no production observability) on PRs #3 and #14 (server-side changes treated as observability concerns). All three rows are written in the same keyword-broad shape v3 retired from R-002 / R-018 / R-019.

**What v4 v1 does NOT do**

This PR ships the honest baseline. The fixes for the three findings above are v4 v2's job — applying the v3 prompt+row sharpening pattern to R-006, R-012, R-013, R-015, and a second-pass sharpening on R-002 to handle the relocation case PR #3 surfaced. Mixing the measurement and the fix in one PR would hide whether the v4 v2 lift came from real improvement or from re-fitting the prompt to the new set.

**Generalisation**

Two methodological points:

- *A small golden set is a benchmark, not a baseline.* The v3 PR claimed F1 0.588 honestly against 4 cases. That was correct given the data; it was wrong as a general statement about the agent. Doubling the set was the cheapest move to find out.
- *Stress-test the previous fix in the new set.* PR #3 was added deliberately because it modifies the exact mechanism R-002 was sharpened to capture. The fact that v3's rule didn't fire on the relocation case is a direct, evidence-led finding for v4 v2 — not a guess about where to look next.

The eval and regression suites stay measurable; the 9-case set replaces the 4-case set in `golden_set.yaml` for all future runs.

### F-015 — R-006 row sharpening lifts F1 0.421 → 0.462; three attempted sharpenings reveal the LLM-tuning ceiling

**Date:** 2026-06-03
**Surfaced by:** Phase 9 v4 v2 — applying the v3 prompt+row-sharpening pattern to the seven rows F-014 identified as v4 v2 targets, then selectively reverting the six changes that didn't help (or hurt) and keeping the one that did.
**Severity:** Moderate (F1 lift is real but small; the more important finding is the methodological ceiling on prompt+register tuning, which is the load-bearing case for phase 13)

**What worked: R-006 sharpening (gap-description → narrow subject-mechanism)**

R-006's row was rewritten from "No service-boundary contract verification for the JSON API — clients drift from the server's actual behaviour" (a *gap* description, mitigated since phase 4) to a *subject-mechanism* description naming the contract surface itself: "The published v1 API contract — OpenAPI spec, endpoint route definitions, request/response schemas, status-code mapping, validation behaviour, error formats — drifts from what clients can rely on. The subject mechanism is *the contract surface itself*: any diff that adds/removes/renames endpoints, changes schema field types or required-ness, alters status-code semantics, modifies OpenAPI metadata, or changes `spec_processor` / response post-processing raises this risk. Server-internal refactors that preserve the published contract verbatim, client-side or internal-data-model changes, and pure security input handling that doesn't shift the documented status codes do NOT raise it".

Effect on the bigger set:

| Case | v4 v1 F1 | v4 v2 F1 | Δ |
|---|---|---|---|
| PR #14 (hide /metrics from spec) | **0.000** | **0.667** | **+0.667** |
| PR #5 (correct API error contract) | 0.400 | 0.500 | +0.100 |
| PR #6 (reject null bytes) | 0.400 | 0.500 | +0.100 |
| PR #12 (F-008 time-of-day) | 0.500 | 0.571 | +0.071 |

Aggregate: F1 0.421 → **0.462** (precision 0.333 → 0.360, recall 0.571 → 0.643). v2 v2 regression remains clean — PR #12's R-011 stably top across all 3 runs (the v3 regression target is preserved).

The pattern works because the new R-006 description names a *concrete, narrow positive surface* (the contract artifacts — spec, schemas, status-code mapping) AND explicit exclusions on adjacent surfaces. Together they give the agent both *what to match on* and *what to skip*.

**What didn't work: three attempted sharpenings, reverted**

1. **R-002 row second-pass + prompt worked example for relocation diffs.** F-014 named PR #3 (booking-service refactor) as the deliberate stress test for v3's subject-mechanism rule. The v4 v2 attempt added "wherever it lives in the codebase: inline in a route handler, in a service module, in a future location" to R-002's row AND added a *second worked example* to the system prompt: "Worked example 2 (relocation): a diff that moves the inline booking-creation logic out of a route handler into a new service module — preserving the check-then-create pattern verbatim — DOES raise R-002". **The agent still emitted R-012/R-013/R-014/R-015 on PR #3 and missed R-002.** Single-shot eval F1 stayed at 0.000.

   Finding: *the agent's first-pass row-matching dominates over the prompt's worked examples*. Adding a counter-example to the system prompt doesn't override pattern-matching on the rows themselves. Subsequent row surgery would have to make R-002 *match more strongly on refactoring keywords* — which risks over-pulling on every server-side refactor, not just booking ones.

2. **R-012 retune to "injection-resistance posture" only.** v4 v2's first attempt sharpened R-012 broadly to cover any AI prompt/schema change. This caused a hard regression on PR #12 (R-011 stably missed in 0/3 runs of the v2 v2 regression — R-012 dominated and crowded R-011 out). A second attempt narrowed R-012 to *guardrail loosening* only, explicitly carving out "adding new fields to capture more user intent" as R-011's territory. **The regression persisted** — the agent still emitted R-012 at relevance 3 on PR #12 and missed R-011.

   Finding: *the agent treats overlapping rows as competing, not co-applicable*. When two rows both legitimately apply to one diff (R-011 for AI correctness, R-012 for injection surface widening), the agent picks one. The prompt's subject-vs-adjacent rule says "match the diff to the mechanism" but doesn't teach "two rows can be raised by one diff if their subjects differ". This is a schema/prompt-architecture limit, not a row-text limit.

3. **R-008 / R-013 / R-015 / R-017 sharpenings (gap-description → subject-mechanism, without narrow positive surface).** All four rows were rewritten from gap-description ("no a11y validation", "no production observability", "fixtures contain real PII", "workflow uses deprecated Node 20 actions") to subject-mechanism descriptions with explicit exclusion clauses. **All four expanded over-pull.** PR #2 went from F1 1.000 to 0.500 (R-018/R-019 over-pulls appeared); PR #11 went from 0.667 to 0.400 (same pattern); R-013/R-014/R-015 over-pulls grew on PRs #3 and #12.

   Finding: *gap-description → subject-mechanism conversion expands positive matches unless the subject mechanism has a narrow concrete surface*. R-006 worked because "the published API contract" is a narrow, concrete surface. R-008's "rendered UI surface" is broader; R-013's "metrics emission and visualisation path" is broader; R-017's "workflow YAML's action-version pins" is narrow but the rewrite added too many positive keywords. The exclusions exist but the agent weights positive matches over negative exclusions.

**The methodological finding**

Three v4 v2 attempts revealed three different limits of pure prompt+register tuning:

- Worked examples in the system prompt don't transfer to row-matching behaviour (R-002 / PR #3).
- The agent's row-matching is *competitive* not *co-applicative* (R-012 / R-011 on PR #12).
- Subject-mechanism row rewrites *expand* matches unless the resulting positive surface is intrinsically narrow (R-008 / R-013 / R-015 / R-017).

Together these are the *LLM-tuning ceiling* for this agent under the current architecture. Each individual failure could plausibly be patched with another iteration; the pattern across three different failure modes is the case that further row+prompt tuning gives diminishing returns. The two highest-impact remaining cases (PR #3 R-002 miss at F1 0.000; PR #11 R-012 over-pull) both share the same root: the agent's row-matching is doing too much of the work.

**Next architectural move (phase 13)**

The natural lever is to take responsibility *away* from the LLM and put it in deterministic code. A **register pre-filter** that classifies the diff by layer/file before the agent sees the register would prevent the agent from ever considering R-018 on a CSS-only PR, R-017 on application code, R-002 on AI-prompt diffs, etc. The agent would only judge between rows the deterministic spine has decided are *layer-relevant*. Tracked as phase 13 (a new phase rather than phase 9 v5 — the change is architectural, not tuning).

**What v4 v2 ships**

- R-006 row sharpened (the one validated technique)
- The v4 v2 attempts and their reverts are documented in this finding rather than in code — the codebase reflects the *outcome*, not the journey
- One incidental code change: `risk_agent/eval.py` handles lone surrogates emitted in the agent's markdown rationale (test data from PR #6 echoed back) with `errors='replace'` on the markdown write. JSON is safe via `json.dumps`' default `ensure_ascii=True`.

### F-016 — Deterministic register pre-filter (phase 13 v1) lifts F1 0.462 → 0.710

**Date:** 2026-06-03
**Surfaced by:** Phase 13 v1 — acting on the F-015 finding that pure prompt + register-text tuning had hit a ceiling, the deterministic spine takes responsibility for *which rows the agent ever considers* on a given diff.
**Severity:** Significant (largest single F1 step in phase 9's history; new failure-mode surface introduced; architectural shift validated by measurement)

**What changed**

A new module `risk_agent/prefilter.py` declares a mapping `R-ID → list of file-path glob patterns` with a rationale comment per entry. The agent's `prioritise()` function now narrows the register before sending it to the LLM, and *also* narrows the structured-output schema's `enum` constraint — so the model physically cannot emit a filtered-out R-ID. A fallback rule preserves recall in the unknown case: if no pattern matches any file in the diff, the full register is sent (and the audit trail flags `prefilter_fallback_used: true`).

The agent's job is now narrower and better-scoped: judge relevance level (2 or 3), write rationale, suggest probes — within a small pre-qualified candidate set. *Layer classification* — which is not genuinely ambiguous; a CSS file is a CSS file — has moved out of the LLM and into deterministic Python.

**Measurement**

| Metric | v4 v2 (no pre-filter) | Phase 13 v1 (pre-filter) |
|---|---|---|
| F1 | 0.462 | **0.710** |
| Precision | 0.360 | **0.647** |
| Recall | 0.643 | **0.786** |
| TP / FP / FN | 9 / 16 / 5 | **11 / 6 / 3** |
| Relevance accuracy | 0.667 | 0.727 |

Per-case wins worth naming:

- **PR #3 (booking refactor): F1 0.000 → 0.667.** The deliberate v3 / v4 v2 stress test that resisted four iterations of prompt + row sharpening. The pre-filter routes `app/routes/member.py`, `app/routes/visitor.py`, `app/services/booking_service.py` to R-002 as a candidate; the agent's smaller candidate set leaves no room for the R-012/R-013/R-014/R-015 over-pulls that previously dominated. R-002 now caught directly.
- **PR #7 (a11y CSS): F1 0.667 → 1.000.** Workflow-mapped rows (R-018, R-019) are filtered out — CSS files don't match those patterns. The agent sees only R-008 + R-018 candidates and picks R-008 cleanly.
- **PR #14 (hide /metrics from spec): F1 0.667 → 1.000.** The pre-filter routes `app/__init__.py` (where the spec_processor lives) to R-006 + R-013 candidates only. The agent picks R-006 at relevance 3 and doesn't get a chance to over-pull anything else.
- **PR #12 (F-008 AI booking): F1 0.571 → 0.857.** R-006, R-011, R-012 all correctly raised; only R-008 missed (the template change is plausibly a11y-relevant but the agent didn't see it that way).

v2 v2 regression remains clean — PR #7 R-008 and PR #12 R-011 both stably top across all 3 runs.

**v1's new failure-mode surface**

Phase 13 v1 *trades* failure modes: agent over-pull goes down; pre-filter false negatives become the new risk class. If a clever PR touches a file path the mapping doesn't recognise as relevant to a row, the agent can't raise that row even if a reviewer would. v1 takes two mitigations:

1. **Fallback to full register** when no pattern matches any file. Better the agent over-pulls than that the pre-filter silently excludes a row. v1 prefers false-positive in the filter (a real bug surfaced during impl: `app/models.py` patterns didn't match `app/models/booking.py` — the project uses a `models/` directory. Without the `app/models/**` widening, PR #8 hit fallback and R-017 was over-pulled. The unit-test suite has a PR #8 regression guard so the same shape can't slip past silently again).
2. **Audit trail in the rendered report.** The agent's per-PR plan now ends with a `Filtered out by pre-filter` section listing every R-ID the deterministic spine excluded. A human reviewer can sanity-check whether any filtered row should have been raised — and sharpen the mapping if so.

The remaining 6 false positives are all *defensible-as-candidates* cases: the pre-filter said "this row could apply" and the agent agreed plausibly, but the golden set says the diff didn't truly raise it. These are v2 mapping-tightening targets (e.g. removing `app/api/schemas.py` from R-011's patterns since contract-only changes shouldn't necessarily trigger AI-correctness review).

**Architectural finding**

Moving layer classification out of the LLM was the right move because *layer classification is not genuinely ambiguous*. A file path is a file path; a route definition belongs to one or two layers, not all of them. The LLM's capability — fuzzy reasoning under uncertainty — was being wasted on the well-posed sub-problem ("which rows even could apply") and that waste was *introducing noise* (the keyword-match-on-row-text over-pulls F-015 documented).

This is the **same pattern that has recurred throughout the harness**:

- F-001: SQLite FK pragma enforcement — deterministic test-environment config beat trusting "in-memory dev should match Postgres prod".
- F-003: Schemathesis contract sweep — deterministic property-based verification beat hand-curated example tests for finding spec/behaviour drift.
- F-005: k6 thresholds-as-code — deterministic performance budgets beat trusting that a smoke test would notice an N+1.
- F-012: Disabling CSS smooth-scroll via init script — deterministic test-environment override beat repeatedly bumping Playwright assertion timeouts on a client-side race.
- **F-016: Register pre-filter — deterministic layer classification beats prompting the LLM to do the same job from scratch on every diff.**

In each case the deterministic move was *narrower* than the original behaviour but *more defendable*. The pre-filter is a code artifact you can read, test (it has its own unit tests), and reason about; the LLM's row selection was a black box that produced opaque over-pulls and stable-divergent cases.

**What v1 deliberately leaves to future iterations**

- **Mapping tightening from v1's 6 remaining false positives.** R-011's `app/api/schemas.py` pattern is the obvious next narrowing; R-007's broad `app/services/**` could be scoped; R-001 currently fires too eagerly on any model change. These are v2 mapping refinements with clear case-level targets.
- **Content-aware filtering beyond paths.** A v3 could parse the diff body and key on AST node types or regex patterns (e.g. "this diff adds a new endpoint route definition" → R-006 candidate even outside `app/api/**`).
- **Confidence-weighted filtering.** Currently binary: a row is in or out. A future iteration could carry a per-row prior into the agent's prompt.
- **Pattern self-tuning.** The mapping is hand-authored. A future enhancement could derive it from historical agent runs + golden-set agreement.

**What phase 13 v1 ships**

- `risk_agent/prefilter.py` — declarative mapping for all 19 R-rows + `candidate_risks(diff) → (kept, filtered_out, fallback_used)` + `_path_matches` helper handling `**` segments.
- `risk_agent/agent.py` — `prioritise()` wires the pre-filter; `AgentResult` carries the audit trail (`filtered_out_ids`, `prefilter_fallback_used`); the LLM schema's R-ID enum is narrowed to the candidate set.
- `risk_agent/render.py` — markdown report includes a `Pre-filter` section listing what was filtered out.
- `tests/test_prefilter.py` — 9 unit tests covering per-layer expectations for the 6 representative PR shapes, the fallback rule, the kept/filtered partition consistency, and the PR #8 `models/**` regression guard. Deterministic code → testable code → first-order benefit of moving classification to the spine.

### F-017 — Mapping tightening (phase 13 v2) lifts F1 0.710 → 0.733; cross-row coupling surfaced

**Date:** 2026-06-04
**Surfaced by:** Phase 13 v2 — acting on v1's 6 remaining false positives, the mapping for R-001, R-011, and R-018 was narrowed to match where the subject mechanism *actually* lives rather than the broader "any file in this layer" patterns v1 used.
**Severity:** Moderate (modest F1 lift; a more interesting structural finding about how pre-filter changes propagate into the agent's reasoning beyond just narrowing its options)

**What changed**

| Row | v1 patterns | v2 patterns | Why |
|---|---|---|---|
| R-001 | `tests/conftest.py`, `app/models/**` | `tests/conftest.py` | FK pragma enforcement is the subject mechanism, configured in conftest only. v1's model-side path fired on query-strategy tweaks (PR #8) that have nothing to do with FK semantics. |
| R-011 | `app/services/booking_assistant.py`, `app/templates/member/book_tee_time.html`, `app/api/schemas.py` | drop schemas.py | AI-feature correctness lives in the assistant + its template. `schemas.py` is contract surface (R-006). The PR #12 case still has R-011 in candidates via the other two paths. |
| R-018 | `app/templates/**`, `app/static/js/**`, `app/routes/member.py`, `app/routes/visitor.py` | drop the route paths | The smooth-scroll race F-012 traced is entirely client-side. Server-side route changes that preserve redirect targets don't affect the race. |

**Headline measurement**

| Metric | Phase 13 v1 | Phase 13 v2 |
|---|---|---|
| F1 | 0.710 | **0.733** |
| Precision | 0.647 | 0.688 |
| Recall | 0.786 | 0.786 |
| TP / FP / FN | 11 / 6 / 3 | 11 / 5 / 3 |

The headline jump is small. The case-level picture has more nuance.

**Per-case wins**

- **PR #6 (reject null bytes): F1 0.500 → 1.000.** Best individual case-level lift. Under v1, the agent over-pulled R-011 on this schemas-only diff and missed R-003. Under v2 R-011 isn't a candidate (no AI-surface paths in the diff), and the agent cleanly catches both R-003 (plausible) and R-006 (direct). The narrower R-011 mapping let the right rows land.
- **R-018 over-pull on PR #3 eliminated.** R-018 is no longer a candidate for booking-route-only diffs — the smooth-scroll race truly lives on the client side.
- **R-001 over-pull on PR #8 eliminated.** R-001 is no longer a candidate for query-strategy model changes.

**The displaced-FP pattern**

In each case where a narrowed mapping removed an FP, **R-007 (performance/latency) became the new over-pull source** on the same case:

- PR #3: R-018 FP → R-007 FP
- PR #5: R-011 FP → R-007 FP
- PR #8: R-001 FP → R-009 FP (a different broad-mapping row)

R-007's mapping (`app/models/**`, `app/routes/**`, `app/api/**`, `app/services/**`) is genuinely broad — performance risk lives anywhere a query pattern can regress, which is *most server-side code*. Path-based filtering can't narrow R-007 without losing real coverage. v3's content-aware filtering — keying on `+from sqlalchemy` / new query patterns / N+1 shapes — is where this gets fixed.

**The unexpected finding: cross-row coupling on PR #12**

PR #12's candidate set is *identical* under v1 and v2 (the v2 R-011 narrowing didn't change PR #12's candidates because PR #12 has booking_assistant.py + template — both still map to R-011). The same `user_message` is sent to Ollama under both versions. Yet:

| Run | Phase 13 v1 ranking | Phase 13 v2 ranking |
|---|---|---|
| Run 1 | `R-011`(3), `R-012`(3), `R-006`(2), `R-008`(2) | `R-011`(3), `R-012`(3) |
| Run 2 | `R-011`(3), `R-012`(3), `R-018`(2), `R-019`(2) | `R-011`(3), `R-012`(3) |
| Run 3 | `R-011`(3), `R-012`(3), `R-018`(2), `R-019`(2) | `R-011`(3), `R-012`(3) |

v2's R-006/R-008 *miss* on PR #12 (3/3 runs) is what dragged that case from F1 0.857 → 0.667. But the candidate set is identical. The system prompt is identical. The register text is identical. The diff is identical. The only thing that changed is *what's in other rows' mappings* — which the agent doesn't see directly.

Working hypothesis: **the agent picks up signal about a diff's "domain" from the relative breadth of candidate rows**, not just their text. Under v1, R-011's broader mapping (including schemas.py) signalled "this diff is in the AI feature's domain" more strongly, which seems to have pulled the agent into emitting *other AI-adjacent rows* (R-006, R-008) at the plausible tier. Under v2, with R-011 mapping narrower to assistant + template only, the same `schemas.py` change reads as less in R-011's domain to the agent, and the tail of the ranking collapses.

This means the pre-filter's effect on agent behaviour is **not just "remove candidates"** — it's also a signal about *what kind of change this is*. That's a v3 design input: when we tighten a row's mapping, we may be unintentionally signalling away from the diff's broader concerns. Possible mitigations:
- Separate "narrowed for matching purposes" from "the agent's perception of the diff's domain" — e.g. always include all candidate rows in the prompt context, but mark which ones the pre-filter considers most direct.
- Restructure the user-message construction to decouple the candidate set from the per-row relevance signal.
- Track this empirically: a v3 pattern would re-test whether further narrowing of one row causes other rows to drop on the same diff.

**What this means for v3**

- **R-007 mapping narrowing** is a v3 candidate but path-based filtering won't solve it cleanly — it needs content-aware shape detection.
- **R-012 PR #11 and R-019 PR #2 over-pulls** still require content-aware filtering (a `booking_assistant.py` non-prompt-change vs an action-version bump are both path-invisible).
- **Cross-row coupling** is a structural design question, not a mapping question. v3 should attempt at least one experiment to confirm or refute the hypothesis (e.g. add a row to candidates artificially and observe whether other tail entries reappear).

**What v2 ships**

- `risk_agent/prefilter.py` — R-001, R-011, R-018 patterns tightened with rationales explaining the narrowing.
- `tests/test_prefilter.py` — PR #3, PR #8 cases updated to reflect v2 expectations; two new regression guards added (schemas-only diff must not raise R-011; template-only diff must still raise R-018).

### F-018 — Content-aware filtering (phase 13 v3) lifts F1 0.733 → 0.929; phase 13 closed

**Date:** 2026-06-04
**Surfaced by:** Phase 13 v3 — F-017's path-ceiling diagnosis named three rows (R-007, R-012, R-019) where path-only filtering couldn't distinguish "genuinely raises the risk" from "lives in the same file as something that does". v3 extends the pre-filter to inspect diff content for those rows, plus R-009 and R-010 (added after the first refresh surfaced their same shape), plus a narrowing of R-002's paths and a comment-line stripping helper.
**Severity:** Significant (largest F1 step since phase 13 v1; phase 13's three-iteration arc closed; F-017's cross-row coupling hypothesis empirically confirmed by side-effect of v3's R-007 change; demonstrates that small targeted callables can break through path-ceiling that pure tuning could not)

**What changed**

The mapping format extended from path-only to `(R-ID, paths, content_filter, rationale)`. Five small Python callables inspect the diff's added lines for marker substrings; a row is a candidate only when path match AND (if a content filter is set) the content filter accepts. Pure-comment lines (`+# ...`) are stripped before matching in the two filters where comment-text false-positives would otherwise bite (R-010, R-019) — a fix discovered when PR #2's first-pass eval still over-pulled R-010 via an explanatory comment that *mentioned* `docker/build-push-action`.

| Row | Content filter scans for | Excludes |
|---|---|---|
| R-007 | SQLAlchemy ORM keywords: `lazy=`, `selectinload`/`joinedload`/`subqueryload`/`lazyload`/`noload`, `.query(`, `db.session.query`, `primaryjoin=`, `secondary=` | Pure logic refactors that move existing queries verbatim |
| R-009 | Schema/constraint markers: `Column(`, `ForeignKey(`, type primitives (`Integer`/`String(`/`Float`/`Date`/`Time`/`Boolean`/etc.), constraint kwargs (`nullable=`/`unique=`/`default=`/`index=`), `CheckConstraint`/`UniqueConstraint`. `relationship(` deliberately excluded — PR #8's lazy-strategy line contains it | Query-strategy changes on existing relationships (PR #8 shape) |
| R-010 | Image build/push/sign markers: `docker`, `cosign`, `ghcr`, `build-push-action`, `Dockerfile`, `image:`, `registry`, `crane`, `syft`. Uses comment-stripped lines | Pure action-version bumps even when their comments mention docker (PR #2 shape) |
| R-012 | Prompt/schema markers: `SYSTEM_PROMPT`, `_PROMPT `, `_PROMPT=`, `system_prompt`, `"system"`, `"enum":`, `"properties":`, `not_before`/`not_after`, `format=` | Helper function changes in `booking_assistant.py` (PR #11 shape) |
| R-019 | Memory-relevant workflow content: `playwright`, `chromium`/`firefox`/`webkit`, `axe-core`/`axe-playwright`, `browser`, `matrix:`, `parallel:`, `container:`, `services:`. Uses comment-stripped lines | Pure action-version bumps (PR #2 shape) |

Two further changes accompany the filters:

1. **R-002's `app/models/**` path removed.** v1/v2 mapped models under R-002 on the theory that uniqueness-constraint changes raise the booking-concurrency risk. PR #8's lazy-strategy tweak demonstrated the displaced-FP shape: any model change qualified R-002 path-only, even when no uniqueness constraint was touched. Reviewed in F-018; a genuine new `UniqueConstraint` would in practice arrive with route or service changes that already match.
2. **`_added_code_lines` helper.** Filters pure-comment lines (`+# ...`) from the lines considered by R-010 and R-019. Discovered when PR #2's diff added a multi-line YAML comment mentioning `docker/login-action` and `docker/build-push-action` purely to explain why the Node 24 env-var toggle was needed — those mentions matched R-010's markers even though no docker step was added.

**Measurement**

| Metric | v1 | v2 | **v3** |
|---|---|---|---|
| F1 | 0.710 | 0.733 | **0.929** |
| Precision | 0.647 | 0.688 | **0.929** |
| Recall | 0.786 | 0.786 | **0.929** |
| TP / FP / FN | 11 / 6 / 3 | 11 / 5 / 3 | **13 / 1 / 1** |
| Cases at F1 = 1.000 | 2 | 3 | **7** |
| Cases at F1 ≥ 0.857 | 3 | 4 | **8** |

**Per-case deltas (v2 → v3):**

| Case | v2 F1 | v3 F1 | What changed |
|---|---|---|---|
| **PR #3 (booking refactor)** | 0.667 | **1.000** | R-007 content filter excludes the pure-logic refactor; R-002 narrowing removes models from the path set |
| **PR #5 (api error contract)** | 0.500 | **1.000** | R-007 excluded from schemas-only changes; agent now catches both R-003 and R-006 cleanly |
| **PR #8 (N+1)** | 0.667 | **1.000** | R-009 filter excludes the lazy-strategy tweak; R-002 narrowing removes the displaced-FP risk |
| **PR #11 (F-007 slot)** | 0.667 | **1.000** | R-012 content filter excludes the helper-function change |
| **PR #12 (F-008 AI)** | 0.667 | **0.857** | R-006 recovered (the cross-row coupling effect, see below); R-008 still missed (LLM calibration) |
| PR #2 (Actions) | 0.667 | 0.667 | R-010/R-019 filtered out; R-005 displaced FP appeared (the agent picks whichever workflow-mapped row still qualifies) |
| PR #7 / #6 / #14 | 1.000 | 1.000 | No content-filtered rules apply at these paths |

**The cross-row coupling result**

F-017 hypothesised that the agent picks up signal about a diff's "domain" from the relative breadth of candidate rows, not just from their text. v3's R-007 narrowing accidentally tested it: PR #12 was missing R-006 under v2 (3/3 runs); under v3 R-007 is no longer a candidate for PR #12 (no query patterns in the diff body), and the agent now stably emits R-006 instead.

Same diff. Same prompt. Same register text. The only change between v2 and v3 (for PR #12) is **whether R-007 sits in the prompt as a "general server-change tail row"**. With R-007 gone, the agent surfaces R-006 instead. That's the coupling effect F-017 named, observed in production rather than via a separate experiment.

The mechanism is sharper than "candidate-set breadth matters" — it's specifically that **broad rows acting as ambient tail-of-ranking choices crowd out more-specific rows on the same diff**. The agent has a budget for "what's worth mentioning" and a broad-mapped row consumes it before a narrower one can. Removing the broad row lets the narrow one surface.

PR #2's R-010 → R-005 displacement reinforced the pattern from the other side: filter one workflow-mapped row out, the agent picks the next workflow-mapped row as its tail choice. Stopping that displacement would require filtering *every* workflow-mapped row except R-017 — pursuing it further would be whack-a-mole on agent calibration rather than pre-filter design, which is why v3 stops here.

This is a *transferable* pattern. Any time a broad-mapped row in the candidate set is *plausibly relevant but not the most specific match*, it can suppress more-specific rows on the same diff (or be displaced by a peer when filtered out). Future row authoring should treat "what other rows compete for the same diff's attention" as a design input.

**What remains (1 FP, 1 FN — both honest LLM-calibration judgments)**

- **R-005 FP on PR #2.** R-005 (CI lint gate) maps to `.github/workflows/**`. PR #2 changes the workflow file. The agent says "lint-gate-affecting change plausible". A reviewer reading the actual diff would see only action-version bumps and a Node 24 env-var toggle, but the agent emits R-005 at 2. Defensible argument from the row's perspective; the golden set sees through it. Pursuing this further with a content filter for R-005 would just displace the FP onto R-014 or R-016 (other workflow-mapped rows). Better tracked as an LLM-calibration item than chased in the pre-filter.
- **R-008 FN on PR #12.** R-008 (a11y) is in PR #12's candidates via the template change. The agent stably doesn't emit it across all 3 v2 v2 regression runs. Single-shot LLM judgment that the template's banner change is incidental to the AI feature work. Not addressable in the pre-filter; would require prompt-level or relevance-rubric work to nudge.

**Why phase 13 closes here**

The three-iteration arc has answered every question phase 13 was designed to investigate:

- **v1:** Does moving classification out of the LLM into deterministic Python lift F1? Yes — F1 0.462 → 0.710.
- **v2:** Does path-based filtering have a ceiling? Yes — F1 only moves to 0.733 under v2, and F-017 articulated the path-ceiling mechanism.
- **v3:** Does content-aware filtering break through the path ceiling? Yes — F1 → 0.929, and 7 of 9 cases now hit 1.000.

The remaining single FP and single FN are agent calibration questions, not pre-filter questions. They sit in the LLM's judgment surface rather than the deterministic spine. The current F1 is well past "good enough to use" and further squeezing would be whack-a-mole on displaced FPs.

Phase 13's broader contribution was demonstrating, with measurement, that *the deterministic spine + LLM judgment* pattern lifts both axes (precision and recall) when the boundary is drawn at "what's not genuinely ambiguous". Future LLM-in-the-loop work in this repo should reach for this pattern first.

**What v3 ships**

- `risk_agent/prefilter.py` — five content filters (R-007, R-009, R-010, R-012, R-019), a `_Rule` dataclass with optional `content_filter` field, an `_added_lines` helper and a comment-stripping `_added_code_lines` helper. R-002's path mapping narrowed to drop `app/models/**`. The 14 path-only rules keep working unchanged.
- `tests/test_prefilter.py` — 10 new tests covering positive + negative cases for each content filter plus the comment-strip regression guard. Per-layer tests updated to reflect content-filtered rows correctly dropping out when the stub body is empty.

### F-019 — Auth-bypass probing (phase 12 deferred-E) surfaces three GET endpoints accepting anonymous traffic

**Date:** 2026-06-04
**Surfaced by:** Phase 12 deferred-E — the `explore_agent.run` auth-bypass pass added a third dimension to API probing (credential mode) alongside the existing happy/edge/abusive payload variants. The pass replays each endpoint's happy payload under three credential modes: `unauth` (no Authorization header), `wrong_creds` (a deliberately invalid bearer token), `other_member` (a different seeded member's valid token, used to probe owner-scoping on resource-id paths).
**Severity:** Material (six unauthenticated 200s across three GET endpoints on first run; specific scope of intent — public-read calendar vs auth defect — needs a product decision)

**What changed**

The auth boundary is now an orthogonal axis on the explore agent, not a fourth payload variant. The shape:

- `Probe.auth_mode` field tagged on every probe row; `send_probe` accepts an `auth_header` override that strips or replaces the session's Authorization header for one call without mutating the session.
- `judge.deterministic_auth_finding` classifies `unauth` and `wrong_creds` probes mechanically — 401/403 → `expected`, 2xx → `auth_boundary_concern` (high), 5xx → `unexpected_5xx`. The LLM is not asked for an answer the rule already provides.
- `other_member` probes go through the LLM judge with an explicit auth-mode context block in the prompt: endpoints scoped to the caller (`/me`-style) returning another member's data is *expected*; specific resource-id paths returning another member's resource is the concern.
- The five-category enum gains `auth_boundary_concern`, ranked above `unexpected_5xx` in the report.
- The login endpoint (`/api/v1/auth/token`) was already excluded from probing at spec-parse time — the auth pass inherits that exclusion automatically.

**Findings on first run**

Six `auth_boundary_concern` hits across three GET endpoints:

| Endpoint | unauth | wrong_creds | Note |
|---|---|---|---|
| `GET /api/v1/competitions` | 200 | 200 | Read endpoint returns the competitions list without any token |
| `GET /api/v1/tee-times` | 200 | 200 | Read endpoint returns the tee-times list without any token |
| `GET /api/v1/tee-times/{tee_time_id}` | 200 | 200 | Single-slot detail returned without any token |
| `GET /api/v1/members/me` | 401 | 401 | Correctly rejects |
| `POST /api/v1/tee-times/{tee_time_id}/bookings` | 401 | 401 | Correctly rejects |
| `POST /api/v1/booking-assistant` | 401 | 401 | Correctly rejects |

`other_member` mode hit `expected` on every endpoint — `/me` correctly returned the other member's profile (the by-design behaviour for an identity endpoint), and the resource-id endpoint (`GET /tee-times/{id}`) returned the same slot data the original member would see, which is the intended public-read shape if the underlying lists are also public-read.

**What this evidence supports**

The three read endpoints accepting anonymous traffic is either:

1. **A deliberate public-read calendar surface** — a golf club might want anonymous visitors to see availability before signing up. In that case the finding strengthens R-003 / R-004 by *negative confirmation*: the auth boundary holds wherever it is meant to hold (writes, identity).
2. **A defect** — a missing `@login_required` (or equivalent) on read routes, surfaced for the first time because no layer until now probed read endpoints anonymously.

Either way, the value of the finding is that it's now *legible* and *durable* — the explore-agent report row shows the exact endpoint, the credential mode, the status, and the deterministic rationale. A reviewer reads the row, makes the call, and the decision is recorded against this artifact rather than relitigated. That is the explore-agent value proposition.

**What v1 ships**

- `explore_agent/probe.py` — `AUTH_MODES` tuple, `Probe.auth_mode`, `send_probe(auth_mode=, auth_header=)` with a sentinel default that preserves backwards-compatible call sites.
- `explore_agent/judge.py` — fifth category `auth_boundary_concern`, `_AUTH_MODE_CONTEXT` per-mode prompt block, `deterministic_auth_finding` for mechanical modes, `judge` routes unauth/wrong_creds to deterministic regardless of `--no-llm`.
- `explore_agent/run.py` — `--username2`/`--password2`/`--no-auth-pass` flags, `_get_token` helper used both for the seed member and the other member, `_auth_pass` runs the happy payload under all three credential modes, `_finding_for` short-circuits unauth/wrong_creds to deterministic.
- `explore_agent/render.py` — `Auth` column on the findings table, `auth_boundary_concern` in the summary table and at the top of `_CATEGORY_RANK`, JSON dump includes `auth_mode`.

**Design choices worth recording**

1. *Orthogonal axis, not a fourth variant.* The existing happy/edge/abusive enum is about *payload shape*; auth bypass is about *credential identity*. Conflating them would force every probe to be a 9-way cross-product (3 payloads × 3 modes), tripling cost for no extra discriminating signal.
2. *Happy payload only.* The auth boundary is best probed with a request the API *would* accept under valid auth. Sending an abusive payload through an unauth probe muddles the question — is the rejection auth-failure or payload-failure?
3. *Deterministic for unauth/wrong_creds, LLM for other_member.* The unauth/wrong_creds rule is mechanical; using the LLM there would only add latency and a chance of misclassification. The cross-member case genuinely needs response inspection, so the LLM judge gets the auth-mode context and decides.
4. *New category, not stuffed into `business_rule_concern`.* An auth bypass is a distinct class of finding with distinct reviewer follow-up. Adding `auth_boundary_concern` lets the report's summary table and the JSON dump separate it from generic business-rule weirdness, at the cost of fragmenting the enum by one element.

**Open work**

- ~~Decision needed on whether the three anonymous-read endpoints are intentional.~~ Resolved 2026-06-04: not intentional — gated in [golf-web-app PR #15](https://github.com/ayyadam/golf-web-app/pull/15) with `@api_bp.auth_required(token_auth)` on all three reads. Spec auto-regenerates from the decorator stack. Downstream k6 perf script fixed in [PR #35](https://github.com/ayyadam/assurance-harness/pull/35) ([`nonfunctional/performance/api_load.js`](../nonfunctional/performance/api_load.js)) — `setup()` trades seeded creds for a bearer token per run. Contract tests verified clean post-fix.
- ~~Open follow-up: a "spec-aware" sharpening of `deterministic_auth_finding` to consult `endpoint.operation.get("security")` so its semantics become "spec/impl auth drift" rather than "any anonymous 2xx".~~ Delivered as F-020 below.
- Auth-pass coverage in the eval golden set is a separate, optional follow-up — the v2 v1 eval baseline (9/18) was set before auth modes existed and doesn't yet score them.
- R-003 and R-004 mitigation text updated in the register to reference this probe surface.

### F-020 — `deterministic_auth_finding` becomes spec-aware; six F-019 concerns flip to `expected` post-fix

**Date:** 2026-06-04
**Surfaced by:** F-019's open follow-up — the v1 of `deterministic_auth_finding` flagged any anonymous 2xx as `auth_boundary_concern`. That conflates two distinct situations: (a) the impl is missing an auth check the spec said it should have, and (b) the impl is correctly serving a documented public endpoint. The v1 has no way to tell them apart, so it over-flags case (b) as a concern.
**Severity:** Material to the agent's signal-to-noise ratio — turns the auth pass from "useful prompt to look" into "useful prompt to act". Without this sharpening, every SUT that intentionally exposes any read endpoint anonymously would have its explore_agent report perpetually littered with false-positive `auth_boundary_concern` rows that the reviewer has to ignore. With it, the report only flags genuine spec/impl drift, and the new `documented_public_endpoint` category lets the reviewer still verify "did we mean for this to be public?"

**What changed**

`Endpoint` (in `explore_agent/spec.py`) gains a `global_security` field populated from the spec's top-level `security` stanza. The OpenAPI inheritance rule is encoded as a new `Endpoint.is_auth_required` property:

| Operation-level `security` | Global `security` | `is_auth_required` |
|---|---|---|
| Present, non-empty (`[{BearerAuth: []}]`) | (any) | True |
| Present, empty `[]` (explicit override) | (any) | False |
| Absent | Non-empty | True |
| Absent | Absent / empty | False |

`deterministic_auth_finding` now consults that property:

| Probe state | `is_auth_required` | Category | Severity |
|---|---|---|---|
| `unauth` / `wrong_creds`, status 200 | True | `auth_boundary_concern` (sharpened rationale: "spec/impl auth drift…") | high |
| `unauth` / `wrong_creds`, status 200 | False | `documented_public_endpoint` (informational) | low (suppressed in report) |
| `unauth` / `wrong_creds`, status 401/403 | (either) | `expected` | low |
| `unauth` / `wrong_creds`, status 5xx | (either) | `unexpected_5xx` | high |

`other_member` probes remain LLM-judged with the existing auth-mode context block — ownership decisions are not derivable from the spec's security stanza alone.

A new `documented_public_endpoint` category enters the enum, ranked between `schema_drift` and `expected` in [`render._CATEGORY_RANK`](../explore_agent/render.py). Its severity is suppressed in both the findings table and the detail section (the same treatment as `expected`) — `low` is a placeholder there, not a graded concern.

**Measurement**

| Probe | F-019 outcome (pre-fix) | F-019 outcome (post-fix, pre-F-020) | F-020 outcome (post-fix, with sharpening) |
|---|---|---|---|
| `GET /competitions` × `unauth` | 200 → `auth_boundary_concern` (high) | 401 → `expected` | 401 → `expected` |
| `GET /competitions` × `wrong_creds` | 200 → `auth_boundary_concern` (high) | 401 → `expected` | 401 → `expected` |
| `GET /tee-times` × `unauth` | 200 → `auth_boundary_concern` (high) | 401 → `expected` | 401 → `expected` |
| `GET /tee-times` × `wrong_creds` | 200 → `auth_boundary_concern` (high) | 401 → `expected` | 401 → `expected` |
| `GET /tee-times/{id}` × `unauth` | 200 → `auth_boundary_concern` (high) | 401 → `expected` | 401 → `expected` |
| `GET /tee-times/{id}` × `wrong_creds` | 200 → `auth_boundary_concern` (high) | 401 → `expected` | 401 → `expected` |

Local `--no-llm` re-run against the rebuilt SUT post-PR-#15: **24/24 probes `expected`** along the deterministic path; the six pre-fix concerns flipped exactly as designed. `documented_public_endpoint` does not appear in this run because the post-fix SUT has no documented-public endpoints — the new category's value lights up on future SUTs / future drift scenarios, and the 11 unit tests fix its branching in place.

A subsequent **full-LLM run** (the first to actually judge `other_member` probes — F-019 was `--no-llm` so its `other_member` rows came from the deterministic status-only fallback) confirms the deterministic path unchanged but surfaces a separate signal-to-noise issue on the LLM-judged `other_member` path: the judge flagged 5 of 6 `other_member` probes as `auth_boundary_concern`, including endpoints the prompt explicitly tells it to treat as expected (`/me` returning the *other* member's profile is the documented behaviour for an identity endpoint; `/competitions` is a shared list resource with no per-member ownership). Sample rationale on `/me`:

> "The response returned the profile of a different member (ID: 3) when an authenticated token for another member was used, indicating that the endpoint does not enforce ownership restrictions as expected."

The judge over-indexes on "another member's data" and under-weights the prompt's explicit `/me` carve-out. This is a *new observation*, not a regression of F-019 (which never exercised the LLM judge on `other_member`), and it's *out of scope* for F-020 — the deterministic sharpening is correct and shippable on its own. The `other_member` over-flagging is logged as open work below.

**Why the new category, and not just a smaller `auth_boundary_concern`**

The v1 of the meta-finding could have just *suppressed* `auth_boundary_concern` on spec-public endpoints and let those rows fall through to `expected`. The problem: an `expected` row is invisible — a reviewer scanning the report sees no rows for those probes and has no prompt to question whether the public-by-design call is the right one. `documented_public_endpoint` keeps the row visible, ranked above `expected` in the summary, and labels it informationally so the reviewer can still answer "is public access the right contract here?" That's a different question from "the spec and impl agree" — the agent helps with both.

**Design choices worth recording**

1. *Inheritance handled in `Endpoint`, not in `deterministic_auth_finding`.* The OpenAPI security inheritance rule (operation overrides global; empty list explicitly disables) is a property of the endpoint, not of the finding function. Encoding it on `Endpoint.is_auth_required` keeps the finding function's logic readable as a state-machine over `(is_auth_required, status, auth_mode)`, and means any future code path that needs "is this endpoint protected?" can ask `Endpoint` rather than re-implementing the rule.
2. *`Endpoint.is_auth_required` collapses scheme details.* The property returns `bool`, not the security scheme name. The decision logic only cares whether *some* scheme is required; whether it's `BearerAuth` or `BasicAuth` doesn't change `auth_boundary_concern` vs `documented_public_endpoint`. If a future use case needs scheme-level granularity, the raw `operation['security']` / `global_security` lists are still available.
3. *11-test unit suite for branching logic, not a single integration test.* `deterministic_auth_finding` is now a non-trivial decision function (4 status branches × 2 spec states × inheritance). [`tests/test_auth_finding.py`](../tests/test_auth_finding.py) pins each branch with a focused unit test plus inheritance cases (global-required inherited, explicit-empty overriding global). The cost of these tests is small and the regression value is real — F-020 is exactly the kind of "subtle semantics" code where future contributors might "simplify" the branching and silently undo the sharpening.
4. *Other-member probe path untouched.* Spec security tells us "auth is required"; it does not tell us "owner-scoping is enforced". A `other_member` probe returning 200 *could* be a legitimate identity endpoint (`/me`) returning the other member's data, *could* be a non-owner-scoped read of public data, or *could* be an owner-scoping bypass. Only response-body inspection can tell. The LLM judge stays in that loop.

**What v1 ships**

- `explore_agent/spec.py` — `Endpoint.global_security` field, `Endpoint.is_auth_required` property, `parse_endpoints` propagates spec-level security through.
- `explore_agent/judge.py` — `documented_public_endpoint` added to `CATEGORIES`; `_SYSTEM` prompt extended with the new category description; `deterministic_auth_finding` reads `probe.endpoint.is_auth_required` and routes to one of four outcomes.
- `explore_agent/render.py` — `documented_public_endpoint` in summary categories and `_CATEGORY_RANK`; severity-suppression list widened from `{"expected"}` to `{"expected", "documented_public_endpoint"}` in both the findings table and the detail section.
- `tests/test_auth_finding.py` — new 11-test suite covering spec-required × all status classes, spec-public × all status classes, explicit-empty-override behaviour, global inheritance, and rationale-content guards on auth_mode naming.

**Open work surfaced by the full-LLM verification run**

- ~~**LLM-judge over-flags `other_member` probes on shared-resource and identity endpoints.**~~ Resolved 2026-06-05 by F-021 below — phase A measurement confirmed the over-flagging was stable (not jitter) across N=3 runs, B1 prompt-tightening eliminated all five false positives, phase C N=3 verification showed the fix is stable.

### F-021 — `other_member` LLM-judge prompt-tightening; 5 stable false-positives → 0 across N=3 verification

**Date:** 2026-06-05
**Surfaced by:** F-020's full-LLM verification run — the first time the agent's LLM judge actually saw `other_member` probes (F-019 was `--no-llm` so the deterministic fallback short-circuited that path). The judge flagged 5 of 6 `other_member` probes as `auth_boundary_concern`, including endpoints the prompt explicitly carves out (`/me`-style identity, shared resources like `/competitions`).
**Severity:** Material to the explore_agent's signal-to-noise ratio — five false-positive `auth_boundary_concern` rows per report drown out genuine concerns and erode reviewer trust. Resolution closes the F-020 open-work item that was the highest-cost remaining noise source on the auth pass.

**Phase A — stability measurement (N=3)**

Before tuning the prompt, measure whether the over-flagging is *systematic* (real prompt-tuning issue) or *jitter* (LLM noise that would shift around on every run). Same evidence-led pattern as phase 13: tune what's stable, leave what's noisy.

| Endpoint | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| `GET /competitions` | `auth_boundary_concern` high | `auth_boundary_concern` high | `auth_boundary_concern` high |
| `GET /members/me` | `auth_boundary_concern` high | `auth_boundary_concern` high | `auth_boundary_concern` high |
| `GET /tee-times` | `auth_boundary_concern` med | `auth_boundary_concern` high | `auth_boundary_concern` high |
| `GET /tee-times/{id}` | `auth_boundary_concern` high | `auth_boundary_concern` med | `auth_boundary_concern` med |
| `POST /booking-assistant` | `auth_boundary_concern` med | `auth_boundary_concern` high | `auth_boundary_concern` high |
| `POST /bookings` (409) | `expected` | `expected` | `expected` |

**Result:** 100% stable on category across runs (severities show minor jitter med↔high but the classifications are identical). The 409 booking-conflict is consistently and correctly classified as `expected` — the model handles *that* case fine; it's the 200-on-shared-or-identity case it stubs on. Verdict: real prompt-tuning issue → proceed to phase B.

**Phase B — sharpen (B1 prompt-tightening)**

Two targeted edits in [`explore_agent/judge.py`](../explore_agent/judge.py):

1. **Sharpen `_SYSTEM`'s `auth_boundary_concern` category description.** The pre-F-021 phrasing was "another member's data returned when ownership should restrict it" — the model was reading "another member" as "different from the seed member" rather than "different from the caller". Replaced with explicit "this does NOT cover identity endpoints like /me (which return the CALLER's data, whoever the caller is) or shared resources like /tee-times or /competitions (which return the same data for every authenticated member)."
2. **Replace `_AUTH_MODE_CONTEXT["other_member"]`** with a decision rule. Four cases enumerated with concrete examples: identity endpoints (caller's own data → expected), shared/catalog endpoints (same data for every member → expected), owner-scoped reads (refuses or filters when caller doesn't own → real concern), and non-auth 4xx/5xx (business logic, not auth → expected). The framing pivots from "different from seed" to "different from caller", explicitly: **"THE CALLER IN THIS PROBE IS THAT OTHER MEMBER."**

The criterion the prompt now lands on: **OWNERSHIP, not "a different token was used"**.

**Phase C — verification (N=3)**

| Endpoint | Pre-fix (phase A) — stable | Post-fix run 1 | Post-fix run 2 | Post-fix run 3 |
|---|---|---|---|---|
| `GET /competitions` | `auth_boundary_concern` | `expected` | `expected` | `expected` |
| `GET /members/me` | `auth_boundary_concern` | `expected` | `expected` | `expected` |
| `GET /tee-times` | `auth_boundary_concern` | `expected` | `expected` | `expected` |
| `GET /tee-times/{id}` | `auth_boundary_concern` | `expected` | `expected` | `expected` |
| `POST /booking-assistant` | `auth_boundary_concern` | `expected` | `expected` | `expected` |
| `POST /bookings` (409) | `expected` | `expected` | `expected` | `expected` |

**Result:** 5 stable false-positives → 0, also stable across N=3. The 409 booking-conflict case continues to classify correctly (no regression in what was already right).

**Side effect — default-mode classifications**

The sharpened `_SYSTEM` category description also affects how the LLM judges *default*-mode probes. Comparing F-020's run to phase C:

| Bucket | F-020 run | Phase C runs (range) |
|---|---|---|
| `auth_boundary_concern` | 5 | **0** |
| `unexpected_5xx` | 1 | 1–2 |
| `business_rule_concern` | 8 | 5–6 |
| `expected` | 22 | 28–30 |

The shift is consistent and in the expected direction: 5 `auth_boundary_concern` rows gone (resolved as designed), 2–3 borderline `business_rule_concern` rows now landing as `expected`. No new concerns appeared. This is the side benefit of a sharper category vocabulary — adjacent ambiguity also tightens. The explore_agent v2 v1 eval baseline (50.0% accuracy on the 18-case golden set) was set before this sharpening; re-baselining the eval is a candidate follow-up.

**Why F-021 worked when the original prompt didn't**

The pre-F-021 prompt *did* include a carve-out: "Endpoints that return data scoped to the caller (e.g. /me) are expected to return that other member's data, which is correct behaviour." Why did the LLM ignore it?

Three reasons, in order of effect:

1. **Framing mismatch.** The prompt said "a DIFFERENT seeded member's valid token was sent" — the model latched onto "different" and read every subsequent token's data as a leak by default. F-021 explicitly states "THE CALLER IN THIS PROBE IS THAT OTHER MEMBER", reframing "the caller" as the source of truth for ownership.
2. **Implicit category, not enumerated.** "Endpoints that return data scoped to the caller (e.g. /me)" is one phrase; the model has to recognise that competitions/tee-times/catalog endpoints are *also* a non-leak category. F-021 enumerates four explicit cases (identity, shared, owner-scoped, business-logic 4xx/5xx) with concrete URL examples for each.
3. **Negative example absent.** The original prompt told the model what a leak *is* but not what it *isn't*. F-021's `_SYSTEM` category description now ends with the explicit exclusion: "This does NOT cover identity endpoints like /me … or shared resources like /tee-times or /competitions."

This is a transferable lesson for future LLM-judge prompts in this repo: **concrete examples + explicit exclusions + caller-as-source-of-truth framing**, in that order, are what made the difference. Future findings work where the LLM's judgement is off-target should reach for this pattern before more invasive deterministic fixes (B2-style).

**What F-021 ships**

- `explore_agent/judge.py` — two prompt edits as described above. No code-path changes; the deterministic spine + LLM-jury structure is unchanged.
- `explore_agent/reports/report.md`, `report.json` — refreshed from phase C run 3.
- This finding + header bump + F-020 open-work resolution.

**What F-021 does NOT do**

- B2 (deterministic shared-resource fence) remains *unused*. B1's prompt-tightening alone resolved the over-flagging stably; the more invasive fix is not warranted. B2 stays documented in F-020's open-work plan as a fallback if a future SUT surfaces a case B1 can't handle.
- ~~The v2 v1 eval baseline (50.0% on 18 cases) is *not* re-baselined here; the phase C side-effect numbers suggest the sharpening tightens default-mode calls too, but that's a separate eval-extension exercise (an F-022-eligible follow-up).~~ Re-baselined 2026-06-05 as F-022 below.

### F-022 — explore_agent v2 v1 eval re-baselined after F-021 prompt-tightening; 0.500 → 0.648 mean across N=3

**Date:** 2026-06-05
**Surfaced by:** F-021's documented "what F-021 does NOT do" follow-up. The phase C side-effect numbers on default-mode probes (8 `business_rule_concern` → 5–6; 1 `unexpected_5xx` → 1–2; 22 `expected` → 28–30) hinted that F-021's `_SYSTEM` sharpening tightens adjacent default-mode ambiguity too, but the eval's accuracy number was set in phase 12 v2 v1 *before* F-020 and F-021. This finding measures the actual lift the F-021 prompt produced on the exact same 18-case golden set, with N=3 to account for LLM jitter.
**Severity:** Significant — provides the new measured baseline for the explore_agent's over-flagging behaviour, identifies which six cases are stably unfixed (the F-023 work-list), and validates the F-021 prompt change moved the eval needle by ~+15 percentage points without code-side eval changes.

**Method**

`python -m explore_agent.eval --refresh` invoked three times back-to-back against the rebuilt SUT. Each invocation does a full LLM run (~5–10 min) then deterministic scoring of the cached `report.json` against `golden_set.yaml`. Per-case category compared across the three runs to separate *stable* outcomes from *jitter*.

**Results — N=3**

| Run | Accuracy | `expected` (correct) | `unexpected_5xx` (FP) | `business_rule_concern` (FP) |
|---|---|---|---|---|
| 1 | 0.667 (12/18) | 12 | 0 | 6 |
| 2 | 0.611 (11/18) | 11 | 1 | 6 |
| 3 | 0.667 (12/18) | 12 | 1 | 5 |
| **Mean** | **0.648** | **11.67** | **0.67** | **5.67** |

**Lift over baseline: 0.500 → 0.648 mean (+14.8 percentage points; +2.67 cases on average).**

**Per-case stability across N=3**

| Outcome | Count | Cases |
|---|---|---|
| Stable correct (3/3 `expected`) | 11 | All `competitions-*` (3), all `members-me-*` (3), `tee-times-list-happy/edge/abusive` (3), `tee-times-detail-happy`, `booking-assistant-happy` |
| Stable wrong (0/3 `expected`) | 6 | `tee-times-detail-edge`, `tee-times-detail-abusive`, `booking-assistant-edge`, `booking-assistant-abusive`, `bookings-create-edge`, `bookings-create-abusive` |
| Jitter (1–2 of 3) | 1 | `bookings-create-happy` (2/3 `expected`; 1/3 `business_rule_concern`) |

**Comparison to baseline — which cases moved**

| Case | Baseline (2026-06-02) | F-022 N=3 | Δ |
|---|---|---|---|
| `competitions-get-abusive` | `unexpected_5xx` (wrong) | `expected` (stable correct) | **fixed** |
| `tee-times-list-edge` | `business_rule_concern` (wrong) | `expected` (stable correct) | **fixed** |
| `tee-times-list-abusive` | `business_rule_concern` (wrong) | `expected` (stable correct) | **fixed** |
| `bookings-create-happy` | `expected` (correct) | 2/3 correct, 1/3 `brc` | mild jitter regression |
| `tee-times-detail-edge` | `business_rule_concern` (wrong) | `business_rule_concern` (stable wrong) | unchanged |
| `tee-times-detail-abusive` | `business_rule_concern` (wrong) | `brc`/`5xx` (stable wrong) | unchanged (shape) |
| `booking-assistant-edge` | `business_rule_concern` (wrong) | `business_rule_concern` (stable wrong) | unchanged |
| `booking-assistant-abusive` | `business_rule_concern` (wrong) | `business_rule_concern` (stable wrong) | unchanged |
| `bookings-create-edge` | `business_rule_concern` (wrong) | `business_rule_concern` (stable wrong) | unchanged |
| `bookings-create-abusive` | `unexpected_5xx` (wrong) | `business_rule_concern` (stable wrong) | unchanged (still wrong, different category) |

Net: **+3 fixed stably, –1 mild jitter regression, 6 unchanged**. The arithmetic on the lift: +3 full points − ~0.33 partial point (the jitter case loses 1/3 of its credit) ≈ +2.67 / 18 = +14.8%. Matches the run-level numbers.

**Pattern in what's stuck — the F-023 work-list**

All six stable-wrong cases are `edge` and `abusive` variants on **write or complex endpoints**:

- `tee-times-detail` (single-object GET): edge/abusive return null or odd shapes; LLM reads "weird response → business rule concern".
- `booking-assistant` (LLM-backed POST): edge/abusive payloads exercise prompt-handling; the LLM judge reads its own peer's response on those inputs as suspicious.
- `bookings-create` (POST with body): edge/abusive payloads produce 409 conflicts or 422 validation rejections; the LLM judge reads 409 specifically as a business rule concern, even though the case is exactly what 409 is for.

These need a third round of sharpening — likely the `_SYSTEM` category description for `business_rule_concern` needs an explicit exclusion: "Validation rejections (422) and resource-state conflicts (409) on `edge` or `abusive` inputs are EXPECTED — the API correctly refused malformed or conflicting requests." Following F-021's transferable pattern (**concrete examples + explicit exclusions + caller-as-source-of-truth framing**), F-023 would be a focused prompt-tightening exercise on the variant axis the same way F-021 was on the auth-mode axis.

**Why the mild jitter on `bookings-create-happy`**

This case was previously stable correct (the baseline marked it `expected`). After F-021, it now flips between `expected` and `business_rule_concern` across runs. The sharpened category vocabulary nudged a borderline call into instability. The case isn't *stably* regressed — the post-F-021 mean is 2/3 correct — but it crossed from "stable correct" to "jitter". This is a known cost of category-vocabulary sharpening: borderline cases get re-decided every run.

A reasonable take: this is acceptable for the +3 stable fixes elsewhere; the case will either stably settle as `expected` with F-023's variant-axis sharpening or it'll become a deterministic mini-finding the eval surfaces.

**What F-022 ships**

- `explore_agent/reports/report.md`, `report.json` — refreshed from F-022 run 3 (final invocation).
- `explore_agent/reports/eval-report.md`, `eval-report.json` — refreshed from F-022 run 3; the recorded baseline becomes 0.667 / 12 of 18 on this snapshot, with the N=3 mean (0.648) the durable summary number.
- This finding + Last updated bump + layer-row baseline annotation.

**What F-022 does NOT do**

- ~~**F-023 — sharpen the `business_rule_concern` category description for edge/abusive variants on write endpoints.**~~ Delivered 2026-06-05 as F-023 below.
- **Extend the eval golden set to include auth-mode cases** (18 → 36). The auth modes were added by phase 12 deferred-E and the F-020/F-021 work means the LLM has been judged stably on `other_member`, but they're not yet in the golden set's expected-category records. Scoring auth-pass coverage in the eval is another candidate follow-up.
- **Compare across models.** This re-baseline is for `qwen2.5:32b-instruct-q4_K_M`. The phase 8 pattern of running the same eval across a model list (`ai_evaluation/`) is a natural fit if a model swap is on the table for the explore_agent.

### F-023 — `business_rule_concern` reframed to "wrongful acceptance"; 6 stable-wrong cases fixed; eval 0.648 → 1.000, non-blinding proven

**Date:** 2026-06-05
**Surfaced by:** F-022's six stable-wrong cases (`tee-times-detail-edge/abusive`, `booking-assistant-edge/abusive`, `bookings-create-edge/abusive`) — all `edge`/`abusive` variants on write or complex endpoints, all stably mis-flagged as `business_rule_concern` (or, once, `unexpected_5xx`) across N=3.
**Severity:** Significant — closes the last cluster of stable false-positives on the API explore agent's default-mode pass and, more importantly, replaces a vague category definition with a principled one ("wrongful acceptance, evidenced") that is both sharper *and* more honest about what the agent is for.

**Phase A — the 6 cases are three distinct failure modes, not one**

F-022's "what's stuck" note predicted a one-line fix (exclude 409/422). Reading the actual LLM rationales showed the failure was richer:

| Mode | Cases | What the LLM did wrong |
|---|---|---|
| **A — refusal read as weakness** | `bookings-create-edge` (409), `bookings-create-abusive` (409) | Read the API *correctly refusing* a request (409 conflict) as a business-rule concern. F-022's predicted target. |
| **B — graceful 2xx read as weakness** | `booking-assistant-abusive` (200), `booking-assistant-edge` (200) | Read the API *gracefully handling* weird input as a concern — an injection prompt safely returning benign candidates (the R-012 structured-output boundary *holding*), or an empty candidate list with no error. |
| **C — probe-mechanics misread** | `tee-times-detail-edge` (200), `tee-times-detail-abusive` (200) | Flagged "I asked for ID 1 / a string ID but the response shows ID 92." The path param is substituted with a real seed ID before the request is sent; the LLM saw only the variant's *stated intent* and the response, never the resolved URL, so it invented a mismatch. The abusive case even misfiled a 200 as `unexpected_5xx`. |

The unifying insight: **`business_rule_concern` should fire on wrongful *acceptance* (a 2xx that should not have succeeded), never on rightful *refusal* (a 4xx) or graceful handling of weird input.** That single principle covers modes A and B. Mode C had a second root cause — an *information gap*: the judge's user message showed the variant's intent and the response, but not the actual resolved request URL.

**Phase B — two surgical edits**

1. **Close the information gap in `_user_message`.** Added the resolved request line (`Actual request sent: {method} {url}`) with a note that the variant rationale is the generator's *intent* while the URL is what was *actually sent* (path/id params already substituted). The judge now evaluates real evidence, not aspiration — directly fixing mode C.
2. **Reframe three `_SYSTEM` category definitions:**
   - `expected` — now explicitly *includes* (a) any 4xx refusal (400/401/403/404/409/422); (b) a 2xx with a schema-valid body on edge/abusive input, even an empty list or a safely-ignored injection string; (c) a 2xx whose ids/values differ from an edge variant's "intent" (params are substituted; judge the actual request/response).
   - `unexpected_5xx` — added the guard "Do NOT use this category for any non-5xx status" (kills the mode-C abusive-detail misfire that filed a 200 as 5xx).
   - `business_rule_concern` — recast around **wrongful acceptance**: the API accepted something it should have refused and the body *proves* it (past-date booking succeeding, a blocked action completing, sensitive/other-member data in the body, internals leaked). A 4xx refusal is the API doing its job, not this category. "Weird input handled without breaking" is `expected`. The judge must **name the specific rule violated and cite the response evidence** before flagging.

**Phase C — verification (N=3)**

| Run | Accuracy | `business_rule_concern` FPs |
|---|---|---|
| 1 | 1.000 (18/18) | 0 |
| 2 | 1.000 (18/18) | 0 |
| 3 | 1.000 (18/18) | 0 |

All 6 stuck cases flipped to `expected`, perfectly stable across N=3. The eval arc: **0.500 baseline (2026-06-02) → 0.648 mean (F-022) → 1.000 (F-023)**.

**The non-blinding problem, and the positive control**

An eval whose golden set is *all-`expected`* (the seeded surface has no defects) cannot, by itself, distinguish a correctly-sharpened agent from a blinded one — an agent that reflexively answers `expected` would also score 1.000. That is a real limitation of this eval, and reaching 18/18 makes it acute. So non-blinding was proven separately with a **positive-control probe**: a synthetic past-date booking returning `201 Created` (`tee_time_date: 2020-01-01`) fed through the live `judge()`. Result:

> **category:** `business_rule_concern` · **severity:** `high` · **rationale:** "The API accepted a booking for a tee time in the past (tee_time_date: '2020-01-01'), which violates business rules as bookings should not be allowed for past dates. The 201 status and confirmed booking indicate wrongful acceptance."

The agent named the rule and cited the evidence — exactly the behaviour the reframe is designed to preserve. The reframe **sharpened, not blinded**: it raised the evidentiary bar (name the rule + cite the body) rather than disabling the category.

**Why the reframe is also the more honest definition**

The pre-F-023 definition ("Response is technically valid per the schema, but the outcome *suggests* a business-rule weakness") invited speculation — the LLM filled "suggests" with unease about anything unusual. The reframe demands a named rule and cited evidence of wrongful acceptance. For a judge whose output is advisory to a human reviewer, "here is the specific rule the API broke and the field that proves it" is a strictly more useful finding than "this looks off." The transferable lesson extends F-021's: **concrete examples + explicit exclusions + evidence-grounded positive criteria** beat vague qualitative definitions for LLM-judge prompts.

**What F-023 ships**

- `explore_agent/judge.py` — `_user_message` gains the resolved-request line; `_SYSTEM` reframes the `expected`, `unexpected_5xx`, and `business_rule_concern` definitions. No code-path changes; the deterministic spine + LLM-jury structure is unchanged.
- `explore_agent/reports/report.{md,json}`, `eval-report.{md,json}` — refreshed from F-023 run 3 (18/18).
- This finding + Last updated bump + layer-row result annotation.

**What F-023 does NOT do**

- ~~**Add a defective golden-set case so the eval measures recall on concerns.**~~ Delivered 2026-06-05 as F-024 below (via the gated-regression-test route).
- **Re-baseline against other models, or extend the golden set to auth-mode cases** — both still open from F-022.

### F-024 — non-blinding positive control made durable: the eval measures precision, this test guards recall

**Date:** 2026-06-05
**Surfaced by:** F-023's verification step. The explore_agent v2 v1 eval reached 1.000, but its golden set is entirely `expected` (the seeded SUT has no defects), so the score measures *precision* (does the agent avoid over-flagging benign responses?) and is structurally blind to *recall* (would the agent still catch a real concern?). F-023 answered the recall question once, manually, with a positive-control probe. F-024 makes that control durable.
**Severity:** Moderate — not a defect fix; a *test-infrastructure* addition that converts a one-off manual check into a standing regression guard. Its value is asymmetric over time: it does nothing until a future prompt change blinds the judge, at which point it is the only artifact in the suite that goes red.

**The gap it closes**

A precision-only eval and a blinded agent are indistinguishable by accuracy alone: an agent that stably answers `expected` to everything also scores 1.000 against an all-`expected` golden set. F-023 proved the agent was not blinded by feeding a synthetic *wrongful-acceptance* probe — a past-date booking the API wrongly accepted with `201` — through the live judge and confirming it still fired `business_rule_concern` with an evidence-grounded rationale. But that was a manual REPL check, run once, leaving no standing guard. Nothing would catch a *future* prompt edit that re-blinds the judge.

**What F-024 ships**

[`tests/agents/test_explore_judge_nonblinding.py`](../tests/agents/test_explore_judge_nonblinding.py) — a gated regression test in the existing `RUN_AGENT_REGRESSION=1` suite, treating the `explore_agent` judge as a third agent under test alongside `risk_agent` and `triage_agent`. It:

- Builds the synthetic past-date-201 probe **in memory** (no SUT needed — only Ollama), so it can exercise the recall direction the live SUT never produces.
- Runs `judge()` N=3 via the shared `_runner.run_n_times` harness.
- Asserts (HARD) schema validity + closed-vocab per run, and (the non-blinding invariant) that the stable *mode* category is `business_rule_concern` with stability ≥ 0.66 — the same jitter-tolerant floor the risk/triage suites use. A 2-of-3 fire still passes; a judge blinded into stably answering `expected` fails with a pointed message ("A prompt change may have blinded the agent").

Local verification: passes, 3/3 runs fired `business_rule_concern` in 16.7 s. Default `pytest` run skips it cleanly (now 35 passed, 5 skipped); it is gated out of CI like its siblings because live LLM calls would flake the gate.

**Why a gated test, not a defective eval case**

F-023 named two routes: (a) a deliberately-defective fixtured probe scored *inside* `explore_agent.eval`, or (b) a gated regression test. Route (b) was chosen because the eval's scorer reads `report.json` produced from a **live** run against the real SUT — there is no live probe that yields a wrongful-acceptance response (the SUT correctly refuses), so route (a) would require teaching the eval to inject fabricated probes, muddying a tier whose whole virtue is "deterministic scoring of what the agent actually emitted against the live surface". A standalone gated test keeps the eval pure (precision, live surface) and puts the recall sentinel where the other agent-under-test guards already live. The two tiers now bracket the judge cleanly: **the eval catches over-flagging regressions; this test catches blinding regressions.**

**What F-024 does NOT do — and why this is the terminus, not a track**

- **It does not characterise recall comprehensively.** One archetype (past-date acceptance) is guarded, not a panel of every concern shape (blocked-action-completed, leaked-internals, cross-member data). Comprehensive recall on an LLM judge is *unbounded* — there is always another archetype, phrasing, or endpoint — so it is correctly framed as an open-ended *track* to open deliberately if ever wanted, not as unfinished F-024 scope. F-024's claim is narrow and complete: "the judge demonstrably still fires on a genuine concern, and a regression that breaks that now goes red."
- **It does not surface in the rendered `regression-report.md`.** That renderer is purpose-built for the risk/triage jitter metrics; wiring a third agent shape into it is cosmetic and was left out to keep this change minimal. The test's pass/fail is the guard; this finding is the evidence.

### F-025 — R-018 re-opened: F-012's smooth-scroll fix was ineffective; CI trace root-causes the lost confirm POST

**Date:** 2026-06-05
**Surfaced by:** A Functional Tests failure on the docs-only README-refresh merge (dev push run [`27024069137`](https://github.com/ayyadam/assurance-harness/actions/runs/27024069137)). `test_member_books_a_tee_time` timed out at `page.wait_for_url("/member/dashboard")` after the confirm click — the R-018 signature, on a risk that had been marked **closed**.
**Severity:** Significant — not for the bug size (one flaky test) but for the lesson: a fix "validated by 5 clean runs" was never actually working, and only a discipline of *reading the real failure artifact* caught it. This is a methodology finding as much as a defect finding.

**Why this finding exists at all — a process the investigation got wrong first**

The honest path to the root cause went through a wrong turn worth recording, because it is the transferable part:

1. **Mischaracterised as a clears-on-rerun flake.** The first instinct was "flaky, rerun it" — the documented R-019 playbook. The rerun **failed identically** (2 consecutive failures on the same SHA, against 1 pass on master). A rerun that does not clear is not that kind of flake.
2. **Over-confident root-cause claim, then a local repro with the wrong lever.** The next instinct was to assert "client-side smooth-scroll CPU-timing race" and reproduce it locally under CPU throttling. **42 local runs — including 10 at 20× CPU throttle — all passed.** The lever was wrong: CDP CPU-throttling slows the *browser*, but a cold-runner SUT-vs-client interaction timing is not raw-CPU-bound, and in any case the suspected slow chain (the POST→commit→302) is *server-side*, which throttling the browser cannot exercise. A clean local run proved nothing.
3. **The decisive move: read the actual trace.** The functional job uploads a `retain-on-failure` Playwright trace. Its network log from the real failure is unambiguous:

   ```
   POST /auth/login            302   272ms
   GET  /member/dashboard      200    14ms
   GET  /member/book-tee-time  200    36ms
   … then only static-asset 304s. No booking POST. Ever.
   ```

   The server was never asked to book. The confirm click's form submission never fired. The failure screenshot corroborates: stuck on the booking page, slot selected, Booking Details rendered, no navigation. This **ruled out** both the transient-infra hypothesis (every other request succeeded in milliseconds) and server-side slowness (the server was never contacted), and **ruled in** a lost client-side click.

**Root cause — and why F-012's fix never worked**

The booking page (`golf-web-app/app/templates/member/book_tee_time.html`) renders `#confirmBookingBtn` (a `type="submit"` button) inside `#bookingFormWrapper`, then on slot-select runs:

```js
setTimeout(() => wrapper.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 50);
```

Playwright's confirm click races that animation on a cold runner and the click is lost — the submit never fires. F-012 diagnosed this *mechanism* correctly but applied a fix that cannot address it: it set CSS `scroll-behavior: auto` on the root. **Per CSSOM, the CSS `scroll-behavior` property is only consulted when `scrollIntoView` is called with `behavior: 'auto'` (or no argument); an explicit `behavior: 'smooth'` argument overrides it.** The booking page passes `'smooth'` explicitly, so F-012's CSS line never disabled this animation. The race was live the entire time; the "5 clean runs" that justified closing R-018 were the same intermittent luck that produces any small run of green on a ~50%-failure flake.

**The methodology lesson (the durable part)**

- *Absence of recurrence in a small window is not proof of a fix* — especially for intermittent failures. F-012 closed R-018 on 5 clean runs; the true failure rate was high enough that 5 greens was unremarkable luck. A fix for an intermittent failure needs either a deterministic mechanism you can argue from first principles, or a much larger validation window — ideally both.
- *Reproduce against the right variable.* A local repro that cannot exercise the suspected cause (here: browser-CPU throttle vs a cold-runner click/animation race) is worse than no repro — a clean result invites a false "it's not us" conclusion. When you cannot reproduce, **read the artifact from the real failure** (trace, screenshot, network log) before theorising further.
- *The trace is the source of truth.* Two competing hypotheses (transient infra; server-side slowness) and one over-confident claim (client CPU race) were all settled in one read of the network log. Uploading `retain-on-failure` traces is cheap; this finding is the payoff.

**The fix (F-025)**

`functional/conftest.py` page fixture keeps F-012's CSS line (it still covers CSS-driven smooth scroll) and adds the layer it was missing — a `scrollIntoView` shim that coerces every call to `behavior: 'auto'`:

```js
const orig = Element.prototype.scrollIntoView;
Element.prototype.scrollIntoView = function (arg) {
  if (arg && typeof arg === 'object') {
    return orig.call(this, Object.assign({}, arg, { behavior: 'auto' }));
  }
  return orig.call(this, arg);
};
```

This is effective regardless of how the call is made — it rewrites the explicit `behavior: 'smooth'` argument the CSS property could not override. Harness-only; the test still exercises the real submit button, form, and handler — only the cosmetic transition is removed.

**Validation — and an honest limit**

Because the race is cold-runner-specific, it **cannot be reproduced locally** (42 clean local runs confirm that), so the fix cannot be validated by a local repro. Validation is therefore by CI evidence: the fix was run through the functional gate across consecutive green runs. R-018 is held at **mitigated, not re-closed** — a deliberate choice this time, applying F-025's own lesson: a mechanism-sound fix whose confidence rests on CI runs rather than a closed-form proof should not claim "closed". If the flake recurs, the escalation is the SUT-side fix (honour `prefers-reduced-motion`, emulate `reduced_motion='reduce'` in the test) — which would also be a genuine accessibility improvement.

**What F-025 ships**

- `functional/conftest.py` — the `scrollIntoView` shim added to the page fixture; the R-018 history and fixture comments rewritten to reflect the re-open and the CSSOM root cause.
- `docs/risk-register.md` — R-018 status closed → **mitigated**, mitigation text rewritten with the trace evidence and the held-at-mitigated rationale.
- This finding.

### F-026 — Adaptive single-step UI exploration: plan-once becomes a policy, eliminating hallucinated selectors

**Date:** 2026-06-06
**Surfaced by:** The v1 v2 UI agent's documented *plan-once-from-starting-page* limitation (Phase 12 sub-roadmap). The committed plan-era report showed three `dead_end` steps on invented selectors across two tours — `#explore-course-link` and `#view-scorecard-link` (public-pages), and `.candidate-slot` (booking-assistant, where the real class is `.booking-slot`) — because the planner referenced elements on pages it had never perceived.
**Severity:** Moderate — an architectural improvement to an advisory, local-only agent (never a CI gate). Its worth is that it removes a whole *class* of false `dead_end`s at the root rather than patching tours one selector at a time, and that the same first run cleanly surfaced the next two limitations (F-027, F-028).

**Plan vs policy — the root cause**

The v1 v2 UI agent was *plan-first*: one LLM call snapshotted the **starting page** and emitted the entire N-step plan up front (`plan_tour`), then a deterministic executor ran every step blindly (`execute_plan`). Because the planner only ever saw the starting page, every selector for a page it had not navigated to yet was a guess; when the guess was wrong the step failed and the judge tagged it `dead_end` — a failure mode baked into the architecture, not the tour. A plan cannot perceive.

v1 v3 replaces this with a **policy**: a perceive→decide→act loop (`run_tour`). Each step it snapshots the *current* page (URL, title, the interactive elements actually present), shows that plus the history so far to the LLM, and asks for exactly **one** next action; it executes that action, re-perceives, and asks again. The model only ever chooses selectors from elements it has just been shown, so hallucinating a selector for an unseen page is **structurally impossible** — the central guarantee. The loop terminates when the LLM emits `finish` (goal reached or stuck, with a reason) or the tour's `max_steps` budget is exhausted; both outcomes are recorded (`finish_reason` / `hit_cap`).

**Evidence — same three tours, before and after**

| Tour | Plan-based (v1 v2) | Policy-based (v1 v3) |
|---|---|---|
| `public-pages` | 6 steps, **2 dead-ends** — invented `#explore-course-link`, `#view-scorecard-link` | 4 steps, **0 failures**, finished deliberately |
| `member-login-dashboard` | 5 steps, 0 failures | 4 steps, **0 failures**, finished at the dashboard |
| `booking-assistant` | 4 steps, **1 dead-end** — invented `.candidate-slot` | 5 steps, **0 failures**, hit the step cap |

Executor failures from hallucinated selectors: **3 → 0**. Every selector the policy chose existed on the page it was perceiving. The before report is preserved in git history; the after is [`explore_agent/reports/ui/report.md`](../explore_agent/reports/ui/report.md).

**What the same run surfaced (now tracked, deliberately out of scope here)**

The first adaptive run did its job *and* made the next two limitations visible — which is the stated value of this agent (limits show up in the report, not as silent skips):

- **F-027 — judge mislabels a successful intermediate fill as `dead_end`.** On the member-login tour, `fill #password` succeeded and the tour went on to finish at the dashboard, but the judge tagged the fill `dead_end` because it stayed on `/auth/login`. This is a *judge* limitation (already documented in the explore_agent README), independent of plan-vs-policy; it just shows every run now that the policy reliably produces the intermediate-fill pattern. Fix: anchor `dead_end` on the executor's `succeeded` signal rather than on an inferred URL change.
- **F-028 — perception covers controls, not result content.** The booking tour reached `/assist` with zero errors but hit its step cap `observe`-ing, because the assistant renders suggested slots as non-interactive `<div onclick=…>` cards (verified in `golf-web-app/app/templates/member/book_tee_time.html`) and `_snapshot_interactive` lists only `a`/`button`/`input`/`textarea`/`select`. The agent could not perceive that slots arrived, so it could not confidently `finish`. This is a *strictly better* failure mode than the plan-based one — graceful budget exhaustion using only real selectors, versus a hard timeout on an invented one. Fix: widen perception.

Bundling either fix would mix three distinct mechanisms (policy, judge prompt, perception) in one change and dilute this result; each is its own focused, evidence-led follow-up.

**What F-026 ships**

- [`explore_agent/ui_probe.py`](../explore_agent/ui_probe.py) — the plan-based `plan_tour` / `execute_plan` (and the `_PLANNER_*` prompt/schema) replaced by the policy: `decide_next_action` (one action from the current page + history), `run_tour` (the perceive→decide→act loop), plus `PageState` / `TourRun` and a `finish` action. `Step` / `StepResult` / `_snapshot_interactive` / `attach_listeners` / `_execute_step` are unchanged. One deliberate behaviour change: the executor now snapshots the page even after a *failed* action, so the next decision can see reality and recover.
- [`explore_agent/ui_run.py`](../explore_agent/ui_run.py) — wires `run_tour` in place of plan+execute, threads the `finish_reason` / `hit_cap` outcome into the report (summary "Outcome" column + per-tour line), relabels "Plan rationale" → "Decision rationale".
- `explore_agent/reports/ui/report.md` + `report.json` + screenshots — regenerated from the first adaptive run.
- [`explore_agent/README.md`](../explore_agent/README.md) — UI surface rewritten plan→policy; known-limitations updated (plan-once hallucination removed; F-027 / F-028 added).
- This finding + sub-roadmap update (v1 v3 delivered; F-027 / F-028 opened) + Last updated bump.

### F-027 — UI step judge keys `dead_end` off the executor's `succeeded` flag

**Date:** 2026-06-06
**Surfaced by:** F-026's first adaptive run. On the `member-login-dashboard` tour, `fill #password` succeeded and the tour went on to finish at the dashboard, yet the step judge tagged the fill `dead_end` — inferring "the form submission did not occur" from the unchanged `/auth/login` URL, overriding the executor's `succeeded=true`. (A pre-existing judge limitation noted in the explore_agent README; F-026's policy just produces the intermediate-fill pattern on every run, so it showed reliably.)
**Severity:** Low–moderate — a precision bug in an advisory, local-only judge (never a CI gate). It hides no real defect; it adds a spurious `dead_end` on a healthy step, which erodes trust in the report. The fix's value is as much the *durable guard* (a gated regression test) as the prompt change.

**The bug, measured (Phase A, N=3)**

Three synthetic `StepResult`s through the live judge established the baseline:

| Fixture | Correct label | Phase A |
|---|---|---|
| successful `fill #password`, stays on `/auth/login` | `expected` | **`dead_end ×3`** (the FP) |
| failed `click` on a missing selector | `dead_end` | `dead_end ×3` ✓ |
| successful `navigate` that advanced | `expected` | `expected ×3` ✓ |

The judge was otherwise sound — it correctly separated a successful navigate from a failed click. The defect was specific: a *successful* step that stayed on the same page was read as "stuck". The FP rationale was explicit: *"Although the password field was filled successfully… the form submission did not occur… leaving the user still on the login page."*

**The fix — and a first attempt that missed (the transferable part)**

The obvious fix was to anchor `dead_end` on `succeeded` inside the category descriptions ("if succeeded=true the step is not a dead_end"). **Re-measured: the FP was still `dead_end ×3`.** The model read the rule but reasoned past it, because it was grading the step against the *whole tour goal* (reach the dashboard) — "still on login → goal not met → dead_end". A rule buried in a category definition did not bind.

What worked was making the selection *procedural and step-local*:
- an explicit **"judge THIS step, not whether the whole tour goal is complete"** rule, stating that the `succeeded` flag is the source of truth and an unchanged URL is NOT evidence of failure; and
- a **`succeeded`-first decision procedure** (5xx → js_error → `succeeded=false` ⇒ `dead_end` → else `succeeded=true` ⇒ `business_rule_concern`/`expected`) placed *above* the category list, so `dead_end` is structurally gated on the executor's truth rather than the model's inference.

**Verified (Phase C, N=5)**

| Fixture | Correct label | After fix |
|---|---|---|
| successful `fill #password` | `expected` | **`expected ×5`** ✓ (was `dead_end`) |
| failed `click` on missing selector | `dead_end` | `dead_end ×5` ✓ (no regression) |
| successful `navigate` | `expected` | `expected ×5` ✓ |

The regenerated report confirms the end-to-end effect: with **identical policy behaviour** (same step counts, so the judge change is isolated), the `member-login-dashboard` and `booking-assistant` tours — whose worst category was `dead_end` purely from this false-positive in the F-026 report — are now `expected`. (Booking still hits its step cap; that is the separate F-028 perception gap, not a `dead_end`.)

The lesson mirrors F-021/F-023: for an LLM judge, a *decision procedure with the authoritative signal named* beats a rule tucked into prose — and the fix must be re-measured, because a plausible sharpening (attempt one) did nothing.

**What F-027 ships**

- [`explore_agent/ui_judge.py`](../explore_agent/ui_judge.py) — `_SYSTEM` gains the "judge THIS step" rule + the `succeeded`-first decision procedure; the `expected` / `dead_end` category text reworded to match. No change to `_user_message` (it already passes `succeeded`).
- [`tests/agents/test_ui_judge_dead_end.py`](../tests/agents/test_ui_judge_dead_end.py) — a gated (`RUN_AGENT_REGRESSION=1`) regression guarding **both** directions: a successful intermediate fill must not be `dead_end`; a failed click must stay `dead_end`. Passes 2/2; default `pytest` now 35 passed / 7 skipped.
- `explore_agent/reports/ui/report.md` + `report.json` + screenshots — regenerated with the fixed judge.
- [`explore_agent/README.md`](../explore_agent/README.md) — the intermediate-fill known-limitation removed (now fixed).
- This finding + sub-roadmap flip (F-027 done) + Last updated bump.

### F-028 — UI agent perceives non-interactive result content (`<div onclick>` booking slots)

**Date:** 2026-06-07
**Surfaced by:** F-026's first adaptive run. The booking-assistant tour reached the `/assist` results page with zero errors but hit its step cap `observe`-ing, because `_snapshot_interactive` queried only `a` / `button` / `input` / `textarea` / `select` — and the assistant renders its suggested slots as `<div class="booking-slot" onclick="selectTeeTime(…)">` cards. The agent literally could not perceive that results had arrived, so it could not confidently `finish`.
**Severity:** Moderate — a capability gap in the advisory, local-only UI agent. It does not produce wrong findings; it leaves a whole tour unable to reach its goal because the goal's evidence is invisible to the agent. The fix's value is making "result content" (not just controls) a first-class part of perception.

**The gap, measured (Phase A, deterministic — no LLM)**

Because perception is a pure function of the page, this was measured directly, with no LLM jitter. Driving the assistant with an in-window query (`"a 2-ball tomorrow morning"` → "30 matching slots"):

| | Count |
|---|---|
| `.booking-slot` elements in the DOM | **30** |
| Slots perceived by `_snapshot_interactive` | **0** |

The agent saw 35 rows of nav/controls and none of the 30 results — the perception gap, isolated.

**The fix**

- [`explore_agent/ui_probe.py`](../explore_agent/ui_probe.py) — `_INTERACTIVE_JS` widened from `a, button, input, textarea, select` to also match `[onclick]`, `[role="button"]`, `[role="link"]`, `[role="option"]`, `[role="menuitem"]` (a comma selector returns each element once, so no dedup needed). Non-standard clickables fall back to `.firstClass` for a selector hint and their text/aria-label for a label, so the 30 slots now surface as `div.booking-slot "07:00"` … "11:50". `_snapshot_interactive` emits `#id` when present, else `.firstClass`. The 80-row cap is retained (booking page: 35 controls + 30 slots = 65, within budget — a noted bound for denser pages).
- [`explore_agent/tours.py`](../explore_agent/tours.py) — the booking tour's example query changed from `"a 4-ball Saturday morning"` to `"a 4-ball tomorrow morning"`. The SUT seeds 7 days of tee times from spin-up (`range(7)` = today … +6); "next Saturday" lands at offset 7 when run on a Saturday, just outside the window, so the assistant returned 0 slots regardless of perception. "tomorrow" is always offset 1, in-window on any seed day — making the tour reproducible rather than dependent on the weekday it runs.

**Verified (Phase C)**

- **Deterministic (perception):** with the fix, the same probe shows **30 of 30** slots perceived (`PERCEPTION GAP: False`). Guarded by [`functional/test_ui_perception.py`](../functional/test_ui_perception.py) — a hermetic Playwright test (`set_content`, no SUT/LLM/seed dependency) asserting `<div onclick>` and `role="button"` clickables are captured while a plain `<p>` is not. Runs in the Functional CI job; 1 passed.
- **End-to-end (policy):** the booking tour now **finishes in 4 steps** (was: hit cap) — fill → click → observe → observe → `finish` ("the assistant has returned plausible candidate slots… without confirming a booking is reached"), worst category `expected`, 0 failed.
- **Guardrail held without a prompt change (verify-first):** with slots now visible, the agent still did **not** click one — no `selectTeeTime`/`.booking-slot` click anywhere; its own rationale cited "stop at the suggestion phase and not confirm." The post-F-027 scope rule sufficed, so no reinforcement was needed.

**A side-observation that is *not* a regression**

The regenerated report shows `public-pages` going `finished (4 steps)` → `hit cap (6 steps)` (all `expected`, 0 failed — it browsed 6 public pages when the goal asked for "at least two"). This is **not** an F-028 effect: a direct check confirmed the homepage and `/course` snapshots gain **0** rows under the widened selector (those pages have no `[onclick]`/`[role]` clickables), so perception there is byte-identical to before. The shift is ordinary LLM non-determinism on an open-ended "browse" goal — the agent sometimes self-terminates early, sometimes explores to the budget. It is recorded as a residual UI limitation (the policy does not reliably `finish` once an open-ended goal's *minimum* is met), not a defect.

**What F-028 ships**

- `explore_agent/ui_probe.py` — widened perception (selector + `.firstClass` hint + non-standard label fallback).
- `explore_agent/tours.py` — in-window booking query.
- [`functional/test_ui_perception.py`](../functional/test_ui_perception.py) — hermetic CI-runnable perception guard.
- `explore_agent/reports/ui/report.md` + `report.json` + screenshots — regenerated (booking now finishes; one stale screenshot removed).
- [`explore_agent/README.md`](../explore_agent/README.md) — perception-gap known-limitation removed (now fixed); the open-ended-goal `finish` behaviour noted.
- This finding + sub-roadmap flip (F-028 done) + Last updated bump.

### F-029 — B1 security gate: shift-left SAST, SCA, secrets, and DAST

**Date:** 2026-06-08
**Surfaced by:** The cross-board enhancement backlog (§13) — security was the single biggest categorical gap (the gate covered correctness, contract, a11y, performance, and data quality, but the only security testing was the explore_agent's auth-bypass probing). B1 was prioritised "start here". This is the first round: **deterministic scanning** (the `security_agent` interpretation layer is a tracked fast-follow).
**Severity:** Significant — adds a whole assurance *pillar*, not a fix. Every PR is now scanned for vulnerable dependencies, leaked secrets, insecure code, and live attack-surface issues, with results as a gating signal + downloadable evidence + GitHub Security-tab alerts.

**What B1 ships — four techniques under `nonfunctional/security/`**

Security is a quality attribute, so it joins the existing non-functional grouping (peer of `accessibility/`, `performance/`) rather than a new top level.

| Technique | Tool | Target | Gate |
|---|---|---|---|
| SAST | Bandit | SUT app code | advisory |
| SAST (deep) | CodeQL | harness Python → Security tab | advisory |
| SCA | pip-audit | SUT requirements + harness env | gate any non-allowlisted |
| secrets | gitleaks | both repos (history + tree) → SARIF to Security tab | hard gate |
| DAST | OWASP ZAP baseline (passive) | running SUT | advisory |

[`nonfunctional/security/scan.py`](../nonfunctional/security/scan.py) is the single source of truth for *what runs* and *how it gates* — runnable locally and in CI, applying the gate via exit code. Three new CI jobs: "Security (SAST/SCA/secrets)" (static — no SUT build), "CodeQL (SAST)", and "Security — DAST (ZAP baseline)" against the running SUT. All validated green.

**The ratchet gating posture**

Security scanners are noisy on day one, so the posture **ratchets** rather than hard-gating everything:

- **secrets → hard gate** (any committed secret fails, now). Baseline: clean (104 commits scanned, no leaks; plain test passwords don't trip gitleaks).
- **SCA → gate any non-allowlisted vuln** (pip-audit's native behaviour; the allowlist controls noise and pins each accepted CVE to a risk row). pip-audit doesn't expose CVSS reliably, so the gate keys on *presence*, not severity; Trivy is the upgrade path if severity-based gating is wanted.
- **SAST (Bandit, CodeQL) + DAST (ZAP) → advisory** — reported, ratchet to gating once the baseline is clean.

**Baseline findings — detect + report (per the locked scope)**

B1 detects and reports; it does not remediate the SUT this round.

- **SCA — 4 CVEs, all allowlisted under R-020:** flask 3.1.0 (CVE-2025-47278, CVE-2026-27205), python-dotenv 1.0.1 (CVE-2026-28684), and the harness's own pytest 8.3.4 (CVE-2025-71176). The SUT bumps are trivial cross-repo changes; the pytest bump is a major upgrade — both deferred and tracked.
- **SAST — triaged to no genuine issues:** 1 medium (`0.0.0.0` bind in `run.py`, expected for a container) + 2 lows confirmed false positives (`api-v1-token` is an itsdangerous *salt*, not a credential; `'Bearer'` is the auth-scheme literal). Advisory.
- **secrets — clean. DAST — ZAP baseline report uploaded as an artifact.**

**Decisions (locked during design)**

Scope = deterministic scanning (the `security_agent` is a fast-follow); SAST = Bandit + CodeQL (CodeQL targets the harness's own Python — cross-repo CodeQL-on-checked-out-SUT was avoided for its commit-SHA-association fragility, the pre-agreed fallback; Bandit covers the SUT); gate posture = ratchet; SCA = gate any non-allowlisted; findings = detect + report.

**What B1 ships**

- [`nonfunctional/security/`](../nonfunctional/security/) — `scan.py` (orchestrator + gate), `sca_allowlist.txt`, `README.md`.
- `.github/workflows/assurance.yml` — three CI jobs; gitleaks SARIF → Security tab (best-effort); reports as artifacts.
- `pyproject.toml` — Bandit + pip-audit dev deps.
- `docs/risk-register.md` — R-020 (dependency CVEs, partially mitigated). This finding + the security layer-table row + Last updated bump + §13 backlog update.

**What B1 does NOT do (tracked)**

- **Remediate the SUT findings** — the 4 CVEs (and any future SUT fixes) are detected + tracked, not fixed (cross-repo, deferred).
- ~~**The `security_agent`**~~ — **Done (B1c, F-030).** The interpretation crown now judges every SAST/SCA finding (verdict + disposition + register R-ID), mirroring `triage_agent`; 7/7 golden-set baseline.
- **bandit / ZAP → Security-tab SARIF** — bandit needs the SARIF-formatter plugin and ZAP needs a SARIF plugin; CodeQL + gitleaks cover the Security tab for now, the rest are downloadable artifacts.

### F-030 — B1c security_agent judges the B1 findings: verdict, disposition, R-ID; 7/7 baseline

**Status:** Done — 2026-06-08.

**Surfaced by:** B1's tracked fast-follow. The deterministic gate (F-029) *detects* SAST/SCA findings but every run leaves the same manual triage: which hits are scanner noise, which dependency CVEs are real, and which register row owns each. F-029 noted three Bandit false-positives by hand (the `TOKEN_SALT` salt literal, the `'Bearer'` auth-scheme word, the container `0.0.0.0` bind) and four real CVEs accepted under R-020. B1c makes that triage automatic and scorable.

**What B1c ships — the agentic crown over `nonfunctional/security/`**

A new top-level agent [`security_agent/`](../security_agent/README.md), the mirror of `triage_agent` applied to security findings instead of CI failures. Same shape: a deterministic heuristic spine (`findings.py` normalises + dedupes every tool's output into one `Finding`), LLM judgement (`judge.py`), markdown/JSON render, a CLI (`run.py`), and a deterministic golden-set scorer (`eval.py`). Per finding the LLM returns:

- **verdict** — `true_positive` / `false_positive` / `expected_by_design` (the headline: turns "3 scary SAST hits" into "0 real, 3 explained");
- **disposition** — `remediate` / `allowlist` / `accept`;
- **candidate_risk_id** — a register cross-reference, closed-vocabulary enum (the model can only pick a real R-ID or `null`, the same guard as `risk_agent`/`triage_agent`);
- **rationale** — grounded in the specific symptom.

**Key decision — the agent runs the scanners *raw*.** The B1 gate (`scan.py`) applies the SCA allowlist *before* it reports, so its output hides the very CVEs that need judging. The agent runs pip-audit raw (no `--ignore-vuln`) so it re-derives the allowlist recommendation itself rather than trusting a human's prior decision: detect-and-suppress is the gate's job, judge-what-was-suppressed is the agent's. Scope is SAST (Bandit) + SCA (pip-audit); secrets (gitleaks, clean here) and the SARIF-only tools (CodeQL, ZAP — CI artifacts) are a documented fast-follow.

**Result — the agent reproduced the hand triage exactly.** Seven findings (3 Bandit + the 4 raw CVEs, flask/dotenv deduped across `requirements.txt` + `requirements-dev.txt`): all three Bandit hits called as scanner noise with the right reason; all four CVEs routed to *accept-and-track* against R-020. The golden set ([`golden_set.yaml`](../security_agent/golden_set.yaml)) is that triage made machine-checkable; the scorer reports per-axis + combined accuracy, deterministic, no LLM in the scoring path.

**Baseline (B1c v1, 7 findings):**

| Metric | Value |
|---|---|
| Verdict accuracy | **1.000** (7/7) |
| Disposition accuracy | **1.000** (7/7) |
| R-ID accuracy | **1.000** (7/7) |
| Combined (all three right) | **1.000** (7/7) |

**Honest caveat on the number.** A small, clean-cut set: three obvious SAST false-positives and four obvious dependency CVEs, no genuinely ambiguous case (a borderline TP, a CVE that should be *remediated now* rather than allowlisted) to stress the judgement. SCA verdicts are nearly free — "a named CVE in a pinned version is real" is a low bar — so the agent's real value on SCA is the *disposition + R-ID*, and the harder calls are the three SAST FPs. The single number is weak; the **process** is the deliverable — a labelled set, a deterministic scorer, and a numeric baseline future changes are measured against, consistent with every other agent tier.

**Model / scope:** `qwen2.5:32b-instruct-q4_K_M`, local-on-demand (Ollama + the SUT checked out as a sibling). Not wired into CI — like the other agents, LLM calls would flake the gate; the deterministic B1 scanners remain the CI enforcement point.

**Files:** new `security_agent/` package (`findings.py`, `judge.py`, `render.py`, `run.py`, `eval.py`, `golden_set.yaml`, `README.md`, committed `reports/{report,eval-report}.{md,json}`); `.gitignore` un-ignores `security_agent/reports/` but keeps `reports/raw/` out (cached scanner JSON echoes SUT source).

**Follow-ups (tracked):** ~~a propose-diff write-back step~~ (done — F-031 below); fold in secrets + SARIF tools (needs a SARIF normaliser); and harder eval cases once the SUT grows a remediate-now or genuinely-ambiguous finding.

### F-031 — security_agent write-back: reconcile the judgement against the live SCA allowlist

**Status:** Done — 2026-06-08.

**Surfaced by:** F-030's tracked follow-up. The agent judges each finding but changes nothing — so its `allowlist` recommendations and the live [`sca_allowlist.txt`](../nonfunctional/security/sca_allowlist.txt) can silently drift. Write-back closes the loop, mirroring `risk_agent`'s propose-don't-apply stance: it advises, a human (or `--apply`) commits.

**What B1c-write-back ships — [`security_agent/writeback.py`](../security_agent/writeback.py)**

Reads the cached judged findings (`reports/report.json`) and the live allowlist, and reconciles them in **both directions**:

- **in-sync** — CVE in the file and the agent agrees (`allowlist`); no action.
- **propose-add** — agent judges `allowlist` but the CVE is not in the file yet → renders the line in the file's format (`CVE   # pkg ver -> fix (R-ID)`), which it can do deterministically because every `allowlist` finding already carries package/version/fix/R-ID (the `fix` field was added to the `Finding` for this).
- **propose-remove (re-arm)** — a line in the file the agent *didn't* encounter this run: the dependency was bumped/removed, so the line suppresses nothing and the gate should re-arm.
- **conflict** — a CVE in the file the agent now judges something other than `allowlist`; flagged for a human, **never auto-changed** (a judgement disagreement is not a mechanical edit).

Default is **propose** (a reconciliation report + unified diff, touching nothing); `--apply` rewrites the file — adding proposed lines and removing only the *stale* (re-arm) entries, both gated behind the flag.

**Result.** The current run reports all four CVEs **in sync, nothing to apply** — exactly right, since the allowlist was hand-written from the same F-029/F-030 triage. The interesting direction is set up deliberately by sequencing: remediating R-020 (the dependency bumps, next) makes raw pip-audit find those CVEs gone, so the next write-back run flips them to *propose-remove (re-arm)* and proposes deleting the now-stale lines. Build → remediate → re-run demonstrates the full **detect → judge → reconcile → re-arm** loop.

**Scope:** SCA allowlist only — a precise, line-based target. Register-row write-back (prose likelihood/impact/mitigation) stays out: a generated stub would be fuzzier than the line-based allowlist and weaker as an auto-proposed artifact.

**Files:** new `security_agent/writeback.py` + committed `reports/writeback-report.{md,json}`; `fix` field added to `findings.Finding` + `render.to_json` (so write-back can render lines); README write-back section + roadmap.

### F-032 — R-020 remediated: SUT dep bumps + writeback re-arms the allowlist to empty

**Status:** Done — 2026-06-08.

**Surfaced by:** F-031's tracked follow-up and the natural next step after detect → judge → reconcile: actually **remediate**. R-020 had been *partially mitigated* — the SCA gate caught the four dependency CVEs but they sat allowlisted with the fix deferred under B1's detect-and-report scope. F-032 applies the fix and closes the loop end-to-end.

**What F-032 ships — the cross-repo remediation + the agent-driven re-arm**

1. **SUT dependency bumps** ([golf-web-app#16](https://github.com/ayyadam/golf-web-app/pull/16), merged to `develop`): Flask 3.1.0 → 3.1.3 (CVE-2025-47278 fixed 3.1.1, CVE-2026-27205 fixed 3.1.3), python-dotenv 1.0.1 → 1.2.2 (CVE-2026-28684), pytest 8.3.4 → 9.0.3 (CVE-2025-71176). Verified before merge: the full SUT unit suite green on the bumped stack — **197 passed, 1 skipped on pytest 9** (the major bump, the only real risk) — and raw pip-audit reporting **zero** vulnerabilities for both requirement files. APIFlask 3.1.0 resolves cleanly against Flask 3.1.3.
2. **The agent re-armed the allowlist itself.** With the bumps on `develop`, the harness's raw scan went clean (3 SAST findings, 0 SCA), so [`security_agent.writeback --apply`](../security_agent/writeback.py) detected all four allowlisted CVEs as **stale (re-arm)** — present in the file, absent from the scan — and removed their lines. This is F-031's re-arm direction firing for real: the committed [`writeback-report.md`](../security_agent/reports/writeback-report.md) shows `propose remove (re-arm): 4` and the applied diff. The allowlist is now **empty**, so the SCA gate hard-fails on *any* new dependency CVE.
3. **R-020 → mitigated** in the [risk register](risk-register.md): detection in place *and* the current vulns remediated, with the gate re-armed as the standing control.

**The full lifecycle, demonstrated.** F-029 detected, F-030 judged (FP-vs-real + disposition + R-ID, 7/7), F-031 built the reconcile tooling, F-032 remediated and let the agent re-arm. **detect → triage → accept/track → remediate → re-arm** — each stage an evidence artifact, the agent driving the last move.

**Honest note on the eval baseline.** The `security_agent` golden set tracks the *live* scan surface, so remediating the four CVEs retired their four eval cases — the agent had judged them all correctly (the 7/7 in F-030 is preserved there and in git history), but they are no longer findings. The active baseline is now **3/3 on the three SAST false-positives** (the live surface); the four SCA cases are retired with a provenance note in [`golden_set.yaml`](../security_agent/golden_set.yaml) rather than left as perpetual "not found" failures. A living eval set shrinking as findings are fixed is correct behaviour, not a regression — the alternative (freezing fixtures to preserve a headline number) was considered and declined in favour of the honest live-surface view.

**Files:** SUT `requirements.txt` / `requirements-dev.txt` (golf-web-app#16); harness `nonfunctional/security/sca_allowlist.txt` (re-armed to empty + header rewritten), `security_agent/golden_set.yaml` (SCA cases retired), regenerated `security_agent/reports/{report,eval-report,writeback-report}.{md,json}`, `docs/risk-register.md` (R-020 → mitigated), this finding.

### F-033 — security_agent goes SARIF-native; gitleaks (secrets) folded in, proven by a positive control

**Status:** Done — 2026-06-08.

**Surfaced by:** F-030's tracked follow-up — widen the agent beyond SAST + SCA to the rest of the B1 toolchain (secrets + the SARIF tools). The grounding check found all three candidate sources currently **clean** (gitleaks 0 results, CodeQL 0 open alerts, ZAP only informational header warnings), so this is a *capability/breadth* increment, not new findings — which shaped both the scope and how it's evidenced.

**What F-033 ships — a SARIF-native agent + secrets**

- **Generic SARIF normaliser** ([`findings.normalize_sarif`](../security_agent/findings.py)): parses any SARIF log (`runs[].tool.driver.name` → tool, `results[].ruleId`/`level`/`message`/`locations` → Finding). SARIF is the industry-standard interchange format, so "the agent ingests any SARIF" is the right abstraction rather than per-tool hacks.
- **gitleaks (secrets)** folded in as a local default (`collect_gitleaks`, skipped gracefully if the binary is absent). Secret **values are redacted** — they never reach a `Finding` field or the committed report; the judge keys off the rule id + file **path**. The judge prompt gained a secrets clause: a match under `app/`/config/deploy is `true_positive` → remediate; one under `tests/`/`fixtures/`/`examples/`/`docs/` is `false_positive` → accept (path-based discrimination, the way a human triages secrets without seeing the value).
- **CodeQL** is ingestible through the *same* normaliser via `--sarif <file>` (fetch the SARIF from GitHub code-scanning), keeping the default local run uncoupled from GitHub/CI. **ZAP** stays out — its DAST baseline does not emit SARIF by default (a separate CI add-on task).

**Evidence — proven by a control, since the live surface is clean.** gitleaks finds nothing in this repo, so the eval can't exercise the secrets path. Two tests fill the gap:
- a non-gated **normaliser unit test** ([`tests/test_sarif_normalize.py`](../tests/test_sarif_normalize.py)) — runs in the CI `pytest` gate, no binary/LLM: asserts a secret finding is redacted (the value never lands on a `Finding`) and a generic CodeQL-shaped SARIF keeps its message;
- a gated **positive control** ([`tests/agents/test_security_secrets_control.py`](../tests/agents/test_security_secrets_control.py), `RUN_AGENT_REGRESSION=1`, mirroring F-024) — feeds the real judge an AWS-key finding at an `app/config.py` path vs a `tests/fixtures/` path and asserts `true_positive` vs `false_positive` respectively, N=3 with a stability floor. Both passed (2/2, stable).

**Honest note — the SAST baseline held, verified against jitter.** Adding the secrets clause to the shared judge prompt risked disturbing the SAST verdicts (the F-021 lesson). One eval run did show `bandit-b105-auth-token-salt` flip `false_positive` → `expected_by_design` (disposition + R-ID still correct — it's a genuinely borderline verdict on the salt literal). Measured N=3: the verdict was stably `false_positive` 3/3, so the one-off was **jitter, not a prompt-induced regression**; the live SAST baseline holds at **3/3**. No prompt sharpening was needed — but the measurement was, rather than trusting a single run.

**Files:** `security_agent/findings.py` (`normalize_sarif`, `collect_gitleaks`, `collect_sarif_files`, `collect_findings` widened; secret-value redaction), `security_agent/judge.py` (secrets clause), `security_agent/run.py` (`--sarif`), new `tests/test_sarif_normalize.py` + `tests/agents/test_security_secrets_control.py`, README, this finding.

### F-034 — B19: the harness becomes a reusable workflow the SUT's pipeline gates on (shift-left wiring)

**Status:** Done — 2026-06-13.

**Surfaced by:** B19 (the queued shift-left item). Until now the two pipelines were disconnected: the harness assured `golf-web-app@develop` only *when the harness changed*, and gated nothing on the SUT. B19 inverts this — a **golf-web-app PR triggers the harness against its own head SHA**, and merge/publish is **gated** on the result.

**What B19 ships**
- **`assurance.yml` → reusable** via a `workflow_call` trigger with optional inputs `harness_ref` + `sut_ref`. Harness self-runs (push/PR) pass neither, so every default reproduces prior behaviour exactly (verified: harness PR #54 ran all 11 jobs green in self-mode).
- **`golf-web-app/ci-cd.yml`** gains an `assurance` job — `uses: ayyadam/assurance-harness/.github/workflows/assurance.yml@v1` with `sut_ref: ${{ github.event.pull_request.head.sha || github.sha }}` — and `build-and-publish` now `needs: [..., assurance]`, so **no image ships unassured**.
- **Branch protection:** a single stable `Assured` aggregator job (`needs: [assurance]`) is the **required status check** (ruleset on `develop` + `master`, no bypass actors), decoupling the required-check name from the harness's internal job list.
- **Pinned to tag `v1`** so harness evolution can't surprise-break the SUT pipeline.

**Three reusable-workflow gotchas — the real engineering content (each cost a CI iteration to surface):**
1. **A bare `actions/checkout` in a *called* workflow targets the *caller*, not the harness.** Every harness job's self-checkout had to become explicit (`repository: ayyadam/assurance-harness, ref: harness_ref || github.sha`); on self-runs the conditional collapses to the default, so no regression.
2. **`github.event_name` in a called workflow is the *caller's* event** (`pull_request`), never `'workflow_call'`. The first gate (`github.event_name != 'workflow_call'`) therefore never skipped the harness-self jobs (Pytest, CodeQL) on the call path — Pytest then ran against the caller's checkout and failed. Fixed by gating on an input the caller always sets: `inputs.harness_ref == ''`.
3. **A reusable-workflow-calling job exposes no single aggregate check context** — only the nested `Assurance (harness) / <job>` checks. Requiring all nine would couple the SUT's branch protection to the harness's job names; the `Assured` aggregator gives one stable context instead.

**Flake guard (so a required gate stays trustworthy):** `pytest-rerunfailures` retries the functional suite **only on transient `TimeoutError`** (the R-018 booking-confirm race), never on assertion failures — mirroring the TS layer's `retries:2`. Without it, R-018 (which recurs on cold runners) would intermittently block legitimate SUT PRs and train "just rerun". A retry-only pass is reported as a rerun, not hidden.

**Evidence (end-to-end, live):** harness PR #54 green in self-mode (backward-compat); SUT PR #17 green in call-mode against its own SHA with Pytest/CodeQL correctly skipped and `build-and-publish` running only after assurance; the `Assured` ruleset enforcing on `develop`; the post-merge `develop` push run fully green. One transient **k6 `exit 137` (OOM)** appeared on a rerun and cleared on the next — an infra flake the narrow R-018 guard doesn't cover; systematic transient handling remains **B9**.

**Files:** `.github/workflows/assurance.yml` (workflow_call + inputs + explicit harness checkout + input-based gating + functional rerun flags), `pyproject.toml` (`pytest-rerunfailures`), `golf-web-app/.github/workflows/ci-cd.yml` (`assurance` + `assured` jobs, gated `build-and-publish`), harness tag `v1`, golf-web-app ruleset "Assurance gate (B19)", this finding.

### F-035 — B3 v1: metamorphic invariance testing of the booking assistant (a second AI-eval method)

**Status:** Done (v1) — 2026-06-13.

**Surfaced by:** B3 — the gap that a fixed golden set, however large, only ever measures point-accuracy on the *exact* phrasings in it. Real users type typos, abbreviations, filler and reordered clauses; the live failure mode of an LLM feature is **inconsistency under natural variation**, which the golden set is structurally blind to.

**What B3 v1 ships — a second evaluation *method*, co-located under AI eval.** Per the placement decision, it lives in [`ai_evaluation/metamorphic/`](../ai_evaluation/metamorphic/README.md) as a sibling method (not a separate top-level pillar — metamorphic *is* AI evaluation), reusing the golden-set eval's `SUTClient` (same black-box `/api/v1/booking-assistant` path). It generates meaning-preserving **variants** of curated seed requests and asserts the structured `BookingIntent` is **invariant**:
- **transforms** ([`transforms.py`](../ai_evaluation/metamorphic/transforms.py)): casing, whitespace, politeness/filler, single-char typos (on non-semantic tokens only — never weekdays/numbers/periods/times/names), and a **curated golf-domain synonym map** (not a generic thesaurus, which would drift meaning and manufacture false violations);
- **relation framework** ([`relations.py`](../ai_evaluation/metamorphic/relations.py)): intent normalisation (period-case + player-order insensitive), equality, and modal reduction; `expected_variant_key` is the single extension point for v2 directional relations.

**The crux — separating a finding from LLM noise.** The model is nondeterministic, so a divergent rephrase could be sampling jitter. Each input is run **N=3** times and reduced to its **modal intent** + a **self-agreement** rate; a variant counts as a violation only when its seed's self-agreement clears a floor (2/3) — otherwise the seed is reported "unstable — excluded from scoring", not as a finding. (Same jitter discipline as the agent regression tests.)

**Result (qwen2.5:32b-instruct-q4_K_M, the harness-standard model — chosen for one coherent model story across the agentic layer):** **86% invariance (51/59 variants)**, and crucially **all 10 seeds were 100% self-consistent** — so the **8 violations are genuine robustness gaps, not noise**. The model scored 94% on the golden set yet is fragile to phrasing. Standouts: `"a threesome on Wednesday, cheers"` parsed **"cheers" as a player name**; `"a round with Dave on Sunday"` resolved to a **different date** under uppercasing, filler, *and* a typo (three independent triggers); casing/filler flipped `group_size` (1→4, 1→2). By transform, the model was perfectly stable to whitespace/synonyms but fragile to casing (85%), filler (80%) and typos (75%) — the actionable axis.

**Evidence + tests.** Committed report under [`ai_evaluation/reports/metamorphic/`](../ai_evaluation/reports/metamorphic/report.md). The transforms + intent machinery are covered by fast, gated unit tests ([`tests/test_metamorphic_transforms.py`](../tests/test_metamorphic_transforms.py), 12 cases) that run in the standard pytest gate (no SUT/LLM) and assert the transforms are meaning-preserving *by construction*. The live run is local-only (real Ollama-backed SUT, model warmed first — the 19GB cold-load otherwise overruns the SUT's Ollama timeout), consistent with the golden-set eval.

**v2 (queued, immediately after): directional relations** — meaning-*changing* transforms (`4-ball → 2-ball` must flip `group_size` and nothing else; `morning → afternoon` flips `period` only) — already accommodated by `relations.py` without restructure.

**Files:** new `ai_evaluation/metamorphic/{__init__,transforms,relations,run}.py` + `README.md`, `ai_evaluation/reports/metamorphic/report.{md,json}`, `tests/test_metamorphic_transforms.py`, reframed `ai_evaluation/README.md` (two methods), this finding.

### F-036 — B3 v2: directional metamorphic relations (meaning-*changing*, the complement to v1 invariance)

**Status:** Done (v2) — 2026-06-14.

**Surfaced by:** B3 v2 — the queued directional follow-up to F-035. Invariance (v1) asks "does a meaning-*preserving* rephrase keep the intent?"; directional asks the complementary question "does a meaning-*changing* rephrase change **exactly the one field it should**, and nothing else?" — which catches a different failure mode (over-reach: changing the target field *plus* collaterally corrupting another).

**What B3 v2 ships.** Five **directional relations** ([`transforms.py`](../ai_evaluation/metamorphic/transforms.py) `DIRECTIONAL`): `period→afternoon` / `period→morning` (`morning ↔ afternoon`), `group:4-ball→threesome` and `group:threesome→foursome` (`group_size`), and `time:9am→11am` (`not_before`). Each is an unambiguous swap (foursome=4, threesome=3), so the expected outcome is not a judgement call. They auto-apply to any seed whose find-phrase is present. The relation check ([`relations.py`](../ai_evaluation/metamorphic/relations.py) `directional_expected_key`) applies the relation's delta to the seed's **modal** intent → the expected key; a **violation** is `variant_modal != expected` — i.e. the wrong field changed, by the wrong amount, or more than the one intended field. Same N=3 jitter discipline and reliable-baseline gating as v1; the report gains a directional score, per-relation correctness, and directional-violation diffs.

**Result (qwen2.5:32b-instruct-q4_K_M): directional 100% (9/9)** — the model reliably applies *explicit* intent changes (period switch, group resize, time-bound shift) without collateral damage. Invariance this run was 92% (54/59).

**Honest reading — the two scores tell a sharp, complementary story.** The model is **good at doing what you explicitly ask** (directional 100%) but **fragile to incidental phrasing** (invariance 86–92%): casing, typos, and filler flip fields the user never touched — most strikingly **date instability** (uppercasing or a typo flips "next Saturday" a full week, `2026-06-20 → 06-27`). Note the invariance headline *moves run-to-run* (F-035's 86% vs this run's 92%) because the LLM is stochastic and each variant's modal is over only N=3 — so the **stable signal is the pattern** (fragility concentrated in casing/typo/filler and in `date`/`group_size`, never in directional changes), not the exact percentage. A higher N (the `--runs` knob, now properly wired alongside `--reliable-floor`) tightens it at linear cost.

**Tests:** +5 gated unit tests (17 total in [`tests/test_metamorphic_transforms.py`](../tests/test_metamorphic_transforms.py)) covering `apply_directional` and the `directional_expected_key` delta (targeted field changes, others untouched). Also wired `--reliable-floor` through reliability (a latent v1 tidy).

**Files:** `ai_evaluation/metamorphic/transforms.py` (`Directional`, `DIRECTIONAL`, `apply_directional`), `relations.py` (`directional_expected_key`), `run.py` (directional pass + scoring + report sections + floor wiring), `tests/test_metamorphic_transforms.py` (+5), `metamorphic/README.md`, regenerated `ai_evaluation/reports/metamorphic/report.{md,json}`, this finding.

### F-037 — B4 v1: resilience / chaos testing (graceful degradation + automatic recovery)

**Status:** Done (v1) — 2026-06-15.

**Surfaced by:** B4 — the first **resilience** pillar. Every prior tier (functional, contract, E2E, metamorphic, k6 load) assumes a healthy stack; chaos is the complement — *inject a fault into the running compose stack and assert it degrades within a stated bound and recovers on its own.* It is the failure-side partner to the k6 load gate (*fast under load?* ↔ *graceful under failure?*) and the test that makes the Phase-11 Grafana stack earn its keep.

**Scope discipline (the design crux).** Chaos degenerates into "break random things" without a bounding rule: **one representative fault per distinct failure *axis* the architecture can exhibit, and only faults with a pre-stated correct behaviour.** The SUT (Flask `web` + Postgres `db` + non-critical observability) collapses to three axes — *dependency gone*, *dependency slow (grey failure)*, *process death*. v1 ships the two pure-`docker`/`compose` axes; the grey-failure axis (toxiproxy latency) is v2. What is **deliberately excluded** (AI-dependency down — already stub-covered; resource exhaustion — no defined contract; observability down — non-critical-path; multi-fault and latency permutations — non-reproducible / combinatorial padding) is itself recorded in the report, so the *shape* of the testing is part of the evidence.

**What B4 v1 ships.** A self-contained top-level [`chaos/`](../chaos/README.md) pillar (mirrors `ai_evaluation/metamorphic/`): `faults.py` (`probe()` classifying 200 / clean-5xx / *hang* / *refused* / leaked-traceback; `ComposeController` for `pause`/`unpause`/`crash`/`up` + `restart_count`; `wait_for_recovery`), `scenarios.py` (two steady-state→fault→recover hypotheses), `run.py` (CLI + markdown/JSON evidence report). **Local-only** (it mutates a live stack) — but the scenario *logic* is fully **gate-tested** with injected fakes (no Docker/LLM) in [`tests/test_chaos_scenarios.py`](../tests/test_chaos_scenarios.py) (+21 tests), so the method is CI-protected even though the live run isn't.

**Finding 1 — DB outage: degrades but does NOT fail fast (real gap).** With Postgres paused, the static route `/` stays 200 (graceful partial availability ✅) and the app recovers instantly on unpause (✅) — but the DB-backed `/course` **hangs to the probe timeout instead of returning a fast clean 5xx** (❌). The app has no DB *client-side* connect/socket timeout, so a dependency outage converts into request hangs (worker exhaustion under real traffic) — and a server-side `statement_timeout` can't help against a *frozen* server, so the guard has to be client-side (psycopg2 connect/socket timeout + a tighter gunicorn worker timeout + a friendly 503 path). Honest, defensible resilience finding. **Recorded as [R-021](risk-register.md) (record-only, decision 2026-06-15)** — the harness surfaces it; remediation is SUT-side and deferred, so the committed chaos report honestly reads 1/2.

**Finding 2 — process death: restart policy works, *once the fault is modelled correctly* (passed).** Killing the web **process from inside the container** (signalling its PID 1) is recovered automatically by `restart: unless-stopped` — `/course` back to 200 in ~2s with **RestartCount 1 → 2** (the unambiguous proof the policy fired, not a coincidence) and a clean DB reconnect. **The methodological catch:** `docker kill` / `compose kill` do **not** trigger the restart policy (Docker flags an operator kill as a manual stop), and a PID-namespace's PID 1 cannot receive SIGKILL from within — so the naïve "kill the container" fault reports a *false* "no recovery". Getting the fault model right is the difference between a real finding and a Docker-semantics artifact; the distinction is documented in the report's fault-model note.

**Result:** 1/2 scenarios pass — process-death recovery confirmed, DB-outage fail-fast gap surfaced. Both are genuine outcomes (cf. B3: the value is honest findings, not a green rubber-stamp).

**Files:** `chaos/{__init__,faults,scenarios,run}.py`, `chaos/README.md`, `chaos/reports/report.{md,json}` (committed evidence), `tests/test_chaos_scenarios.py` (+21), `.gitignore` (`!chaos/reports/` allow-list, like the other pillars), this finding.

## 12. Roadmap

The full phased plan lives in conversational notes; the abbreviated public form:

| Phase | Goal | Status |
|---|---|---|
| 0 | assurance-harness skeleton (uv, pytest, ruff, CI) | **Done** |
| 1 | Test strategy + risk register | **Done** |
| 2 | golf-web-app JSON API + OpenAPI spec | **Done** |
| 3 | Playwright user journeys (functional) | **Done** |
| 4 | Schemathesis contract tests | **Done** |
| 5a | Accessibility (axe) sweep + gate in CI | **Done** |
| 5b | Performance (k6) budgets in CI | **Done** |
| 6 | Data quality (pandera) on the live database | **Done** |
| 7 | golf-web-app AI feature (natural-language booking, local Ollama) | **Done** |
| 8 | AI evaluation harness | **Done (v1)** — deterministic + LLM-judge (holistic + fuzzy) |
| 9 | Risk-prioritisation agent (PR diff → ranked test plan) | **Done (v4 v2)** — v2 v1 deterministic `covered_by` + `is_gap` and relevance scale; v2 v2 golden-set eval tier; v3 subject-vs-adjacent prompt rule + R-002/R-018/R-019 sharpened (F1 0.526 → 0.588, 4-case); v4 v1 golden set 4 → 9 cases (honest baseline F1 0.421); v4 v2 R-006 sharpened (F1 0.421 → 0.462, methodological ceiling documented in F-015). Architectural next step (deterministic register pre-filter) tracked as phase 13. PR-comment Action deferred (needs hosted-LLM commitment) |
| 10 | Triage agent (CI failure clustering) | **Done (v1 v2)** — v1 v1: heuristic clustering + LLM category + R-ID xref. v1 v2: golden-set eval tier with deterministic scorer. 5/5 baseline on five real failures from last 30 days |
| 11 | Prometheus + Grafana observability stack | **Done (v1)** — local stack scraping the SUT, provisioned dashboard with SLOs aligned to the k6 gate; closes R-013. Loki + Alertmanager deferred to v2 |
| 12 | Exploratory testing agent + tests of agents | **Done (v1 v1, v1 v2 → v1 v3, v2 v1, v2 v2)** — UI agent re-architected plan→policy (v1 v3, F-026); see sub-roadmap below for deferred-but-tracked work |
| 13 | Deterministic register pre-filter for the risk_agent | **Done (v3) — phase closed** — v1 added [`risk_agent/prefilter.py`](../risk_agent/prefilter.py) path-based filtering (F1 0.462 → 0.710). v2 tightened R-001/R-011/R-018 mappings (F1 → 0.733). v3 added content-aware filtering for five rows (R-007, R-009, R-010, R-012, R-019), narrowed R-002's paths, and added a comment-line stripping helper after PR #2's diff revealed marker-words-in-comments cause FPs. **F1 → 0.929** (precision 0.929; recall 0.929); 7 of 9 cases at F1 1.000. F-017's cross-row coupling hypothesis empirically confirmed by v3's eval. See [F-016](#f-016--deterministic-register-pre-filter-phase-13-v1-lifts-f1-0462--0710), [F-017](#f-017--mapping-tightening-phase-13-v2-lifts-f1-0710--0733-cross-row-coupling-surfaced), [F-018](#f-018--content-aware-filtering-phase-13-v3-lifts-f1-0733--0929-phase-13-closed) |

### Phase 12 sub-roadmap

The exploratory testing arc has its own sub-roadmap because the agentic surface has more dimensions than the deterministic spine. Tracked here so deferred items don't drift across PR descriptions and READMEs.

| Sub-phase | Goal | Status |
|---|---|---|
| v1 v1 | Exploratory agent — **API surface**: OpenAPI-driven, LLM payload variants per endpoint, LLM-judged responses | **Done** ([`explore_agent/reports/report.md`](../explore_agent/reports/report.md)) |
| v1 v2 | Exploratory agent — **UI surface**: Playwright tours, LLM plan + LLM judgement per step | **Done; superseded by v1 v3** — plan-once hallucinated selectors for pages it had not perceived |
| v1 v3 | Exploratory agent — **UI surface, adaptive**: replace the upfront plan with a perceive→decide→act *policy* (one action per step from the current page) | **Done** ([`explore_agent/reports/ui/report.md`](../explore_agent/reports/ui/report.md)); hallucinated-selector dead-ends 3→0. See [F-026](#f-026--adaptive-single-step-ui-exploration-plan-once-becomes-a-policy-eliminating-hallucinated-selectors) |
| v2 v1 | **Golden-set eval tier** for the explore agent — mirrors [`risk_agent.eval`](../risk_agent/eval.py) and [`triage_agent.eval`](../triage_agent/eval.py) (deterministic scorer, no LLM in scoring) | **Done** — baseline 50.0% accuracy (9/18); [`explore_agent/reports/eval-report.md`](../explore_agent/reports/eval-report.md) |
| v2 v2 | **Adversarial regression tests on existing agents** — run `risk_agent` / `triage_agent` N times against fixed inputs, assert invariants hold across LLM jitter | **Done** — 12/12 schema-valid, 12/12 closed-vocab, 100% top-result stability; [`tests/agents/reports/regression-report.md`](../tests/agents/reports/regression-report.md) |

Phase 9 v3 (delivered — fix to the issue surfaced by phase 12 v2 v2):

- **Phase 9 v3 — `risk_agent` subject-vs-adjacent rule + sharpened risk rows.** **Done.** Added a subject-vs-adjacent discrimination rule to the system prompt and sharpened R-002, R-018, and R-019 register rows to name their subject mechanisms (transaction boundary at POST /book, Playwright/functional layer's interaction with post-click client-side behaviour, hosted-runner memory ceiling) rather than just listing keyword surfaces. F1 0.526 → 0.588 across the same 4 cases (precision 0.417 → 0.500; recall unchanged at 0.714; relevance accuracy preserved at 0.800). v2 v2 regression: PR #12's stable-divergent warning quieted — R-011 now stably top across all 3 runs. See [F-013](#f-013--risk_agent-subject-vs-adjacent-rule--sharpened-rows-lift-f1-0526--0588) for the full diagnostic + lesson.

Beyond v2, deferred-but-tracked work:

- ~~**Adaptive single-step exploration mode**~~ — **Done (v1 v3, F-026).** The plan-once UI agent committed to a multi-step plan from the starting page's interactive elements only, so selectors on pages it had not seen were hallucinated (the booking-assistant tour waited for the invented `.candidate-slot` while the real class is `.booking-slot`). Replaced with a perceive→decide→act *policy*: the LLM decides one action per step from the current page, making invented selectors structurally impossible. First adaptive run: hallucinated-selector dead-ends 3→0 across the three tours. The decision was taken without waiting on the eval-quantification gate originally noted here — the plan-era report's three invented-selector dead-ends were sufficient evidence on their own. See [F-026](#f-026--adaptive-single-step-ui-exploration-plan-once-becomes-a-policy-eliminating-hallucinated-selectors).
- ~~**Judge: anchor `dead_end` on the executor's `succeeded` signal**~~ — **Done (F-027).** The step judge tagged a *successful* intermediate `fill #password` as `dead_end`, inferring "stuck" from the unchanged URL and overriding `succeeded=true`. Fixed with a `succeeded`-first decision procedure plus a "judge THIS step, not the whole tour" rule — a first attempt that only reworded the category text did not move the model. Verified N=5: the FP → `expected` 5/5, a genuine failed click → `dead_end` 5/5; guarded by a gated regression test ([`tests/agents/test_ui_judge_dead_end.py`](../tests/agents/test_ui_judge_dead_end.py)). See [F-027](#f-027--ui-step-judge-keys-dead_end-off-the-executors-succeeded-flag).
- ~~**Wider page perception — interactive controls *and* result content**~~ — **Done (F-028).** `_snapshot_interactive` listed `a` / `button` / `input` / `textarea` / `select` only, so the booking assistant's suggested slots (`<div onclick=…>` cards) were invisible and the tour capped without perceiving them. Widened the selector to `[onclick]` + interactive `[role]`s; deterministically the slots went from 0 → 30 perceived, and end-to-end the booking tour now finishes (4 steps) while still respecting "do not confirm" (no slot click — the post-F-027 scope rule sufficed, no prompt change needed). The tour's example query was also moved in-window (`Saturday` → `tomorrow`) since the 7-day seed window makes "next Saturday" unreachable when run on a Saturday. Guarded by a hermetic Playwright test. See [F-028](#f-028--ui-agent-perceives-non-interactive-result-content-div-onclick-booking-slots).
- **Free-form UI exploration mode** — the LLM picks goals from a surface map of the SUT instead of running fixed tours.
- **State-mutating tours** — booking confirmation, admin flows, visitor registration. Held out of v1 because the SUT state would drift across runs and the report would not be reproducible.
- **Cross-tour memory** — each tour currently starts fresh. A finding from one tour could in principle inform the next tour's plan or goal selection.
- ~~**Auth-bypass probing on the API surface**~~ — **Done (deferred-E).** Each endpoint's happy payload is re-sent under `unauth` / `wrong_creds` / `other_member`. First run surfaced six anonymous-read 200s across three GET endpoints (decision pending: deliberate public-read calendar or auth defect). See [F-019](#f-019--auth-bypass-probing-phase-12-deferred-e-surfaces-three-get-endpoints-accepting-anonymous-traffic).

## 13. Enhancement & capability backlog (prioritised)

This consolidates future work into one prioritised view: **net-new capability areas** (whole pillars the harness does not yet cover) plus the **existing deferred enhancements** (also tracked in their phase rows / the Phase 12 sub-roadmap). Prioritisation weighs *impact* (how much it raises framework quality), *effort*, *distinctiveness* (signal for an assurance portfolio), and *leverage* (reuse of the existing CI + SUT-spin-up infrastructure).

**Where the harness is strong vs thin.** The current gate covers functional correctness, contract conformance, accessibility, performance, and data quality, plus the AI-evaluation and agentic layers. Three industry-standard pillars are thin or absent — **security** ("is it safe?"), **test-suite effectiveness** ("are the tests themselves any good?"), and **AI-feature robustness** ("does the AI behave under variation/attack?", given the SUT's one AI feature) — and a few narrower techniques are missing.

### Net-new capability areas

- **B1 — Security / DevSecOps gate.** **Deterministic scanning done (F-029):** Bandit + CodeQL (SAST), pip-audit (SCA, gate any non-allowlisted), gitleaks (secrets, hard gate), OWASP ZAP baseline (DAST), under `nonfunctional/security/` with ratchet gating — all green in CI. **Security-triage agent done (B1c, F-030):** [`security_agent`](../security_agent/README.md) judges every SAST/SCA finding (verdict FP-vs-real + disposition + register R-ID), 7/7 golden-set baseline. **Write-back done (F-031):** reconciles the agent's `allowlist` judgement against the live `sca_allowlist.txt` and proposes a diff (`--apply` to commit). **R-020 remediated (F-032):** the four CVEs fixed via SUT dep bumps, and `writeback --apply` re-armed the allowlist to empty — full detect→triage→remediate→re-arm lifecycle. **SARIF-native + secrets (F-033):** generic SARIF normaliser; gitleaks (secrets, redacted) folded in as a local default; CodeQL ingestible via `--sarif`; proven by a hermetic positive control. **Remaining:** ZAP (DAST) ingestion needs its SARIF add-on wired in CI; CodeQL auto-fetch from the code-scanning API. Trivy (severity-based SCA) is an optional refinement.
- **B2 — Mutation testing. Deprioritised (2026-06-13) — pushed down the list.** mutmut / cosmic-ray against the SUT's logic to measure whether the suite *catches* injected bugs (kill rate). Real, respected technique, but ranks poorly for this portfolio's goals: low marginal signal on a small SUT, niche in everyday commercial practice, and — decisively — it's **white-box** (needs SUT source + unit tests + matching language), the *least portable* pillar to the kind of black-box automation contract work being targeted. Kept on the board, not next.
- **B3 — Metamorphic testing of the AI feature. ✅ Done (v1 + v2) — F-035, F-036.** A second eval method co-located under [`ai_evaluation/metamorphic/`](../ai_evaluation/metamorphic/README.md), reusing the eval's `SUTClient`; jitter-disciplined (N=3, modal intent, self-agreement floor). **v1 invariance (F-035):** meaning-*preserving* rephrasings (casing/whitespace/filler/typos/curated synonyms) must keep the intent — 86–92% invariance, real robustness gaps not noise (e.g. "…, cheers" parsed as a *player name*; casing/typos flipping the resolved date a full week). **v2 directional (F-036):** meaning-*changing* rephrasings must change exactly one field and nothing else — **directional 100% (9/9)**. Combined story: the model is good at *doing what you explicitly ask* but fragile to *incidental phrasing* — exactly what the technique exists to surface.
- **B4 — Resilience / chaos testing. ✅ Done (v1) — F-037.** A self-contained [`chaos/`](../chaos/README.md) pillar that fault-injects the running compose stack and asserts graceful degradation + automatic recovery — *one representative fault per failure axis* (scope discipline; exclusions recorded in the report). **v1** ships the two pure-`docker` axes: **DB outage** (`pause db` → `/` stays up, recovers on unpause, but `/course` *hangs* instead of failing fast — a real no-statement-timeout gap) and **process death** (in-container kill of PID 1 → `restart: unless-stopped` recovers in ~2s, **RestartCount** proves the policy fired; note `docker kill` is an operator-stop the policy ignores, so the fault must be modelled in-container). Local-only run, gate-tested logic (+21 tests). **v2** = the grey-failure axis (Postgres latency via toxiproxy) + assert the SLO/Grafana panel breaches (ties to R-013).
- **B5 — Visual regression testing.** Playwright `toHaveScreenshot` baselines on key pages — the agent already captures screenshots but never diffs them.
- **B6 — Cross-browser + responsive.** Run functional tests on firefox / webkit + mobile viewports (chromium-only today; near-zero extra code in Playwright).
- **B7 — Static type-check gate (mypy / pyright).** The codebase is heavily type-hinted but only runtime-checked (typeguard); a static gate is a cheap, standard addition.
- **B8 — Test-authoring agent.** A new agent *role*: read a PR / spec and **write** Playwright / pytest tests — closing the loop from `risk_agent` ("what to test") to the test itself.
- **B9 — Systematic flake detection.** A tier that runs the suite N× and quantifies a flake budget, versus the ad-hoc R-018 / R-019 firefighting.
- **B10 — Stateful / sequence API testing.** Schemathesis-stateful or Hypothesis-stateful to exercise call *sequences* (create-then-cancel honouring spec links), deeper than per-endpoint conformance.
- **B19 — Cross-repo shift-left wiring (SUT-PR-triggered, gating assurance). ✅ Done — F-034.** Today the harness assures `golf-web-app@develop` *when the harness changes* (`assurance.yml` checks out the SUT at a moving `ref: develop`); the two pipelines are disconnected and the harness gates nothing on the SUT. Real shift-left inverts this: a **SUT PR triggers the suite against its own code**, and the result **gates merge/release**. Mechanics: (1) **Trigger + target** — convert `assurance.yml` to a reusable `workflow_call` workflow parameterised on the SUT ref/image (the five `ref: develop` checkouts → `ref: ${{ inputs.sut_ref || 'develop' }}`), and add a caller job to `golf-web-app/.github/workflows/ci-cd.yml` (`uses: ayyadam/assurance-harness/.github/workflows/assurance.yml@v1` with `sut_ref: ${{ github.event.pull_request.head.sha }}`, pinned tag so harness evolution doesn't surprise-break SUT PRs); (2) **Assure the artifact** — build-once-test-the-artifact: publish `ghcr.io/...:<sha>` as the immutable *candidate*, run the harness against it, promote `:latest` / deploy only on green (resolves the publish-vs-test circularity); (3) **Gate** — make the assurance jobs **required status checks** via a golf-web-app branch-protection ruleset, and gate deploy behind a protected Environment so the image cannot ship unassured. Pair with a **flake policy** (retry-once + quarantine; `triage_agent` classifying flake-vs-defect) so the gate stays trusted (cf. R-018, which would otherwise block legitimate PRs and train "just rerun"); run `risk_agent` on the diff as an advisory PR comment (deterministic spine gates, agentic layer advises). Alternative topology for separate-team ownership: `repository_dispatch` round-trip + Statuses-API commit status (looser, async). ~30 lines of YAML across two repos; the single most direct demonstration of the "shift-left of assurance" competency. Documented from the 2026-06-08 design discussion.
- **B20 — TypeScript / Playwright E2E layer (first scheduled piece of the G2 polyglot track). ✅ Done.** Add a second, **TypeScript** expression of the functional E2E pillar alongside the existing Python `pytest-playwright` journeys, making the harness deliberately **polyglot** (Python where it's superior — data/AI/security/agentic; TS/Playwright for web E2E where the market gates on it) and giving a direct **same-journey-in-two-languages A/B**. Rationale traces to **G2** (TypeScript is a recurring screen-level gate on modern-web automation roles; Playwright is the bridge since the harness already uses its Python binding and the model is near-identical across languages). **Layout — a self-contained top-level `e2e_ts/` pillar** (matches the capability-per-directory convention; do **not** nest it inside `functional/` — a Node project wants its own root — and do **not** move the working Python files, which would churn a green suite for cosmetics): `e2e_ts/{package.json, package-lock.json, playwright.config.ts, tsconfig.json, tests/*.spec.ts, pages/ (page objects), README.md}`, with the README cross-referencing `functional/` as its Python counterpart. **Scope — port a representative 2–3 journeys, not all five** (e.g. the member booking journey + public pages, optionally access control); `functional/` stays the primary complete functional layer, `e2e_ts/` is a focused, well-crafted demonstration slice — maintaining full parity is ongoing cost for little extra signal. **G1-ready from commit one (this is what makes it rewrite-proof under a later G1 generalisation):** `baseURL` lives in `playwright.config.ts` read from `process.env.SUT_BASE_URL` (localhost default), **all navigations relative** (`page.goto('/member/dashboard')`), **credentials/test data from env** (never inlined), **resilient selectors** (roles / `data-testid`). These are idiomatic Playwright practices regardless of G1, and they *are* the only SUT-specific seam G1 would parameterise — so a future SUT profile simply supplies those env values and the `.spec.ts` files do not change. (G1 generalises the *engine around* the journeys; the journeys are the irreducibly per-SUT layer and survive as golf-web-app's profile artifacts — see G1.) **CI — one new parallel job in `assurance.yml`:** against the same ephemeral SUT the existing jobs spin up, `cd e2e_ts && npm ci && npx playwright install --with-deps chromium && npx playwright test`, emitting its HTML report + traces into the existing committed-evidence artefact model (`e2e_ts/reports/`, mirroring the other pillars' `reports/` handling in `.gitignore`). Clean toolchain separation from the Python jobs — no shared deps, no interference. **Known limitation:** a server-rendered Flask UI supports TS **E2E** but not isolated **UI-component** testing (which needs a component framework); that one line-item would only be unlocked by a future small TS frontend slice, gated on real JD demand (see G2). **Effort:** days, not weeks; highest near-term career-leverage (clears the recurring TS keyword screen while the Python agentic/data/AI work remains the differentiator). Documented from the 2026-06-12 design discussion.

- **B21 — Page Object Model for the Python `functional/` suite (triggered by coverage growth).** **Deliberate current choice — a dual-idiom split, not an oversight:** the Python `functional/` suite uses idiomatic **pytest fixtures** ([functional/conftest.py](../functional/conftest.py) — `login`, `member_page`, `member`, the R-018 `page` shim), while the TS `e2e_ts/` layer uses idiomatic **Playwright POM + a NavBar component object**. Each suite follows its own ecosystem's native convention, which *demonstrates both conventions intentionally* rather than mechanically copying one into the other. Keeping it this way now is the right call: the fixture layer already centralises the most-reused interaction (login selectors live once in the `login` fixture), each remaining inline locator (`#confirmBookingBtn`, `.booking-slot`) appears exactly **once** across the ~5-file suite (so "centralising" it yields near-zero benefit), and refactoring a green, R-018-mitigated evidence suite for stylistic parity is churn risk for no behavioural gain (over-POM is its own anti-pattern at this scale). **Trigger to revisit:** when the Python functional coverage **grows** — in particular more journeys / repeated traffic through the **member and admin dashboards**, where the same locators and actions start recurring across tests — introduce POM into the Python suite (page objects for the recurring pages, e.g. a `BookingPage` / `DashboardPage`, keeping the fixtures for cross-cutting concerns). At that point the locator-centralisation and readability payoff turns real and POM earns its keep. Until then: documented, not scheduled. Surfaced from the 2026-06-12 dual-idiom discussion.

### Existing deferred enhancements (tracked in their phases)

- **B11 — State-mutating UI tours** (Phase 12 sub-roadmap) — booking confirmation, admin, visitor registration; now feasible via `seed.py`'s clean reset.
- **B12 — Free-form UI exploration** (Phase 12) — the LLM picks goals from a surface map instead of fixed tours.
- **B13 — Cross-tour memory** (Phase 12) — carry findings between tours; best paired with B12.
- **B14 — Open-ended-goal self-termination** (F-028 residual) — the policy should `finish` once a goal's minimum is met; carries an under-exploration risk.
- **B15 — Eval golden-set auth-mode cases** (18 → 36) — score the `unauth` / `wrong_creds` / `other_member` axis, not just payload variants.
- **B16 — risk_agent PR-comment Action** (Phase 9) — post the ranked test plan on PRs; gated on a hosted-LLM commitment (CI cannot reach local Ollama).
- **B17 — Observability: Loki + Alertmanager** (Phase 11 v2) — log aggregation + alerting on SLO breaches.
- **B18 — golf-web-app ruff migration** (flake8 → ruff) — housekeeping/consistency.

### Prioritisation

| Tier | Items | Rationale |
|---|---|---|
| **Done** | ~~**B1 — Security gate**~~ · ~~**B20 — TypeScript / Playwright E2E layer**~~ · ~~**B19 — Cross-repo shift-left wiring**~~ · ~~**B3 — metamorphic AI testing (v1+v2)**~~ · ~~**B4 — chaos/resilience (v1)**~~ | B1: SAST/SCA/secrets/DAST + `security_agent` (F-029–F-033). B20: the `e2e_ts/` TS/Playwright pillar, polyglot A/B with `functional/`. B19 (F-034): `assurance.yml` is now a reusable `workflow_call` the SUT's PR pipeline gates on (build-publish `needs: assurance`; `Assured` required-status-check ruleset on golf-web-app; pinned `@v1`; functional flake guard). B3 (F-035 invariance + F-036 directional): metamorphic testing of the booking assistant — invariance 86–92% with real robustness gaps, directional 100%. B4 v1 (F-037): the `chaos/` pillar — DB-outage fail-fast gap + process-death auto-recovery (RestartCount-proven); toxiproxy grey-failure axis is v2. |
| **Start here next** | **B5 visual regression** · **B11 state-mutating tours** · **B4 v2 chaos (toxiproxy)** | B4 v1 done (F-037). Strongest remaining net-new pillars: visual regression and the state-mutating risk surface; B4 v2 adds the grey-failure (latency) axis + SLO-breach assertion. |
| **Tier 2 — strong / good leverage** | B11 state-mutating tours · B5 visual regression · B4 v2 chaos (toxiproxy latency) | Reach the real (mutation-path) risk surface, add the visual pillar, and complete the chaos grey-failure axis. |
| **Quick wins — low effort** | B7 mypy gate · B6 cross-browser/responsive · B15 eval auth-mode cases | Cheap, standard, round out coverage; good for momentum. |
| **Later / situational** | B8 test-authoring agent · B9 flake detection · B10 stateful API · B12 free-form · B13 cross-tour memory · B14 self-termination · B16 PR-comment Action · B17 Loki/Alertmanager · B18 ruff migration · B21 POM for Python functional (coverage-triggered) | Higher effort, narrower, dependency-gated, triggered, or housekeeping. |

**Steer — B1, B20, and B19 are done.** B1 (F-029–F-033): the deterministic SAST/SCA/secrets/DAST gate + `security_agent`. B20: the `e2e_ts/` TypeScript/Playwright pillar alongside Python `functional/` (the polyglot G2 posture made real). **B19 (F-034): the harness is now a reusable `workflow_call` that golf-web-app's PR pipeline calls against its own head SHA, with `build-and-publish` gated behind it and a required-status-check ruleset (`Assured`) on the SUT — assurance is now an enforced, automated property of every SUT change before merge/ship, the literal shift-left.** **B3 is also done — both v1 and v2** (F-035 invariance + F-036 directional): metamorphic testing of the booking assistant under `ai_evaluation/metamorphic/`. Invariance 86–92% over meaning-preserving rephrasings (real robustness gaps — casing/typos flip the resolved date; "…, cheers" becomes a player name), directional 100% (explicit one-field changes applied cleanly). Net: the model is good at *doing what you explicitly ask* but fragile to *incidental phrasing*. **B2 (mutation testing) was deprioritised** (white-box, low contract-portability — see its entry). **B4 v1 is also done (F-037):** the `chaos/` resilience pillar surfaced a real DB-outage fail-fast gap (a paused DB makes `/course` hang — no statement timeout) and confirmed process-death auto-recovery via the restart policy (RestartCount-proven, with the `docker kill`-is-an-operator-stop fault-model subtlety handled correctly). **The strongest remaining net-new pillars are B5 (visual regression) and B11 (state-mutating tours); B4 v2 (toxiproxy grey-failure latency + SLO-breach) completes the chaos axis.** Broader transient-flake handling (a known k6 OOM surfaced once during B19) remains **B9**.

### Strategic track — generalising the harness for multi-application use (G1)

> This sits **outside** the prioritised B-list above and is deliberately *not* tier-ranked against it. The B-items add capability *depth* to a harness aimed at one SUT; G1 is a different axis — *reach*. It is a strategic re-platforming (productising the engine so it can assure **any** application), gated on a business decision rather than a portfolio-signal trade-off, and it is a programme of work, not a discrete change. Tracked here so the architecture is captured; not scheduled.

- **G1 — Generalisation / multi-SUT productisation.** **Goal:** turn the harness from "a thing built for `golf-web-app`" into a reusable engine that can be pointed at an arbitrary application — the prerequisite for using it across multiple clients/engagements. **Core architectural move: invert the dependency.** Today the harness *embeds* knowledge of the SUT; generalising means extracting everything SUT-specific into a declarative **SUT profile** (e.g. `assurance.yaml`) + a small set of **adapter hooks**, leaving a domain-agnostic engine — the line between a *script* and a *framework* (Pytest/Playwright are frameworks precisely because they know nothing about your app). The profile declares: base URL(s)/environments, OpenAPI spec path, auth recipe, routes to crawl (a11y), perf scenarios + SLO thresholds, SUT repo + language/stack (security), DB DSN + data-quality contracts, which pillars are enabled, and the locations of the agent golden sets + risk register. Product surface becomes `assurance run --profile ./assurance.yaml` (CLI / container / reusable CI workflow). **The reuse is uneven — and that's the key insight:** anything *spec- or wire-driven* generalises almost for free (API-contract off OpenAPI = highest reuse; a11y/axe against any URL = high; k6/perf = config-only), whereas anything that *encodes domain meaning* is bespoke per app (Playwright **journeys** = lowest reuse, they encode real flows/selectors/auth; pandera **data-quality** expectations; the **risk register**). **Polyglot:** the harness *language* (Python) is irrelevant for wire-level pillars (it tests a Java/.NET/Node app fine over HTTP/browser/DB); only **source-reading** tools need a language matrix (Bandit is Python-only → Semgrep or a stack-keyed tool set; SCA/secrets are mostly ecosystem-aware already). **Agentic layer** generalises in *mechanism* (the deterministic-spine + LLM-judge + closed-vocab + golden-set + jitter skeleton lifts as-is) but not in *trust* — each agent needs a **per-app golden set** to be credible, so generalising = a fast golden-set bootstrapping process per engagement. **Data-residency blocker to resolve up front:** the `security_agent` (and any source-reading agent) sends client source to an LLM — local model (Ollama, already used) vs hosted is a confidentiality/contract question, both a selling point and a potential blocker. **Stop owning bring-up:** the engine should *consume* a running environment (take a base URL + optional DB DSN as inputs) rather than start one (`docker compose` + `seed.py` is SUT-specific); the client owns standing-up + seeding — B19's reusable `workflow_call` is already the CI-shaped version of this inversion. **Distribution models, cheapest → most ambitious:** (1) CLI + library (`pip install`, engine + per-client profile repo — already ~80% there); (2) container image (bakes in axe/k6/scanners/browsers, solves the polyglot toolchain); (3) reusable CI workflow / GitHub Action / GitLab template (one job per client — small step from B19); (4) SaaS (hosted runners, multi-tenancy, secrets vaulting, dashboards — only worth it with several aligned clients). **Honest framing:** ~60–70% of the *value* (API-contract, security triage, a11y, the agentic pattern, the evidence/reporting discipline) generalises with a config + adapter layer at modest cost; the remaining ~30–40% (journeys, seed data, domain assertions, risk register, golden sets) is irreducibly bespoke per engagement — but **that bespoke layer is the billable consulting service, not overhead**. So the harness is positioned as an **accelerator / IP** (stand up contract testing, security scanning, a11y gating, and agentic triage in *days not months*, then spend billable time on the high-judgement domain work), not a turnkey zero-effort product. **Cheapest concrete first step if ever scheduled:** extract a single `assurance.yaml` and route the **API-contract + a11y** pillars through it — those two prove the whole config-driven model with the least effort, since they're already near-app-agnostic. Documented from the 2026-06-12 design discussion.

### Strategic track — TypeScript / polyglot language positioning (G2)

> Also **outside** the prioritised B-list and not tier-ranked. Where G1 is about *reach across applications*, G2 is about *language alignment with the market* — a positioning question about which language(s) the harness (and the skills it demonstrates) should be expressed in. Like G1 it is gated on direction rather than a portfolio-signal trade-off, and captured here so the rationale is on record; not scheduled.

- **G2 — TypeScript / polyglot positioning.** **Observation:** a large share of web-focused automation roles ask for either TypeScript *applications under test* or harnesses *written in TypeScript itself*. **This is substance, not fashion — four real drivers:** (1) **shared language with the app** — modern frontends are TS (React/Angular/Vue), so a TS harness can *import the app's own types* (compile-time-safe API clients/DTOs that break when the app changes a field — a Python harness re-describes those types and drifts), and shares one toolchain (`package.json`, ESLint, Node, CI); (2) **whole-team shift-left** — if developers live in TS, tests in TS means they actually write and maintain them, versus the older siloed "throw it to a separate QA suite" model the industry is moving away from; (3) **the dominant E2E tools are JS/TS-first** — Cypress is TS-only; Playwright is multi-language but TS-first in docs/community gravity, so the market coalesced there (network effect on top of the substance); (4) **types make test code maintainable at scale** — the market wants *Type*Script specifically (not raw JS) because large page-object/fixture/client suites need autocomplete + refactor-safety + compile-time checks on the *test* code. **Where Python still genuinely wins (don't trade this away):** data quality / data-pipeline assurance / ML-AI testing (pandas, pandera, Great Expectations); property-based testing (Hypothesis) and API-contract fuzzing (**schemathesis**); backend-Python SUTs (Django/FastAPI/Flask — the shared-language argument flips); and security/orchestration glue. So language preference **tracks the SUT's stack and the team's stack** — web-frontend → TS; data/ML/backend-Python → Python; it is not ideological. **Implication for this harness's positioning:** (a) **Playwright is the bridge** — the harness already uses `pytest-playwright`, and Playwright's model (locators, auto-waiting, fixtures, traces) is near-identical across languages, so a TS port of the journey layer is mostly *syntax*, not a new mental model; (b) keep Python for the **differentiated** layer (the agentic LLM-judge + golden-set + jitter pattern, data quality, AI eval) which most TS-only automation candidates can't build; (c) be realistic that many **JD/ATS keyword screens literally gate on "TypeScript"/"Cypress"/"Playwright"** — a TS/Playwright artifact clears the screen, after which the architecture/judgement (language-transferable) is what wins. **The hybrid / polyglot option — a deliberate, marketable position, not a hedge:** TS/Playwright for the **UI/E2E layer** (shares the app's stack + types, devs can contribute) + Python for **data-quality, AI/ML eval, security-scanner orchestration, and property-based API testing** (where Python is superior), the two layers communicating via **artifacts** (JSON reports) and a **shared CI + shared reporting** (e.g. Allure, which is language-agnostic). The harness is *already* implicitly polyglot — the steer permits "best-in-class tool DSLs (k6/JS) when config-like", and k6 scripts are JavaScript. **Cost to be honest about:** two toolchains / dependency managers / CI surfaces, and it's harder to hire one maintainer for both — which is exactly why some teams pick one language for simplicity; so present hybrid only as a *justified* "right-tool-per-layer" choice, never as indecision (framed that way it signals *more* maturity than a monolingual harness, since it shows tool selection by fit). **Cheapest concrete first step if ever scheduled:** a small TS/Playwright artifact — a parallel journey layer driving the *same* SUT, or a separate minimal repo — to clear the keyword screen and demonstrate cross-language Playwright fluency, while the Python agentic/data/AI work remains the differentiator. **Net position:** *"modern TS E2E **and** the Python data/AI assurance most automation engineers can't do"* is a stronger market stance than either language alone. Documented from the 2026-06-12 design discussion.

## Appendix A: Glossary

- **SUT** — system under test. Here: `golf-web-app`.
- **Harness** — assurance code that targets the SUT. Here: `assurance-harness`.
- **Service boundary** — an interface where one component's responsibility ends and another's begins. We assert at boundaries because that's where contracts live.
- **LLM-judge** — an LLM prompted to score another model's output against a rubric. Used in `ai_evaluation/` where deterministic asserts don't fit.
- **Golden set** — a curated input/expected-output dataset used to evaluate models against a known baseline.
