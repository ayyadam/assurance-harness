# Test Strategy — golf-web-app

**Status:** living document — updated as the assurance harness matures.
**Owner:** Adam (acting as Digital Assurance Engineer)
**Last updated:** 2026-05-27

---

## 1. Purpose

This document describes how we assure the quality of [golf-web-app](https://github.com/ayyadam/golf-web-app) — the system under test — using the [testing-system](https://github.com/ayyadam/testing-system) harness. It exists to:

- Make our assurance approach explicit so delivery decisions can be informed by it
- Give a hiring panel reviewing this portfolio a clear picture of *judgement*, not just tooling
- Provide a stable reference that newer artifacts (test suites, dashboards, reports) link back to

It is deliberately a *living* document — every phase of work updates the relevant section and adds findings to §11.

## 2. System under test

`golf-web-app` is a Flask + SQLAlchemy + Postgres web application for managing a golf club: tee-time bookings, competitions, coaching, range bays, and membership requests. Server-rendered Jinja templates with Bootstrap, Flask-Login for authentication, Docker Compose for the local stack, GitHub Container Registry for image distribution.

Two planned additions extend the assurance surface:

- A small JSON API (`/api/v1/...`) so service-boundary contract testing has something to assert against
- A natural-language booking feature backed by an LLM with tool-calling so the AI-evaluation harness has something real to evaluate

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
| Contract | **Planned (phase 4)** | Schemathesis vs OpenAPI | `testing-system/contract/` | Verify the planned JSON API conforms to its spec under property-based inputs |
| UI / E2E journeys | **Planned (phase 3)** | Playwright + pytest | `testing-system/functional/` | Anchor user-facing assurance for booking, membership, admin flows |
| Accessibility | **Planned (phase 5)** | axe-playwright | `testing-system/nonfunctional/accessibility/` | Budget violations as code, fail PRs that regress a11y |
| Performance | **Planned (phase 5)** | k6 or Locust | `testing-system/nonfunctional/performance/` | Define throughput/latency budgets for hot paths, fail on regression |
| Data quality | **Planned (phase 6)** | Great Expectations / pandera | `testing-system/data_quality/` | Validate seed and snapshot data conform to documented expectations |
| AI evaluation | **Planned (phase 8)** | LLM-judge + golden set + deterministic assertions | `testing-system/ai_evaluation/` | Evaluate the planned natural-language booking feature against a rubric |
| Production observability | **Planned (phase 11)** | Prometheus + Grafana + Loki | `testing-system/observability/` | Assess running systems and capture assurance evidence from production-style telemetry |
| Tests of the harness itself | **Stub (phase 0)** | pytest | `testing-system/tests/` | The harness is software too. Agents and judges get tested like any other component |

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
| Playwright | UI / E2E browser automation | Pending phase 3 |
| Schemathesis | Property-based API contract testing | Pending phase 4 |
| k6 | Performance load generation | Pending phase 5 |
| axe-playwright | Accessibility checks | Pending phase 5 |
| Great Expectations / pandera | Data quality | Pending phase 6 |
| GitHub Actions | CI/CD on both repos | Yes |
| GHCR | Container artifact storage | Yes |
| Prometheus + Grafana | Production-style observability | Pending phase 11 |

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
- Pytest with JUnit + HTML reports uploaded as artifacts

In later phases the `assurance.yml` workflow will pull the GHCR image of golf-web-app, bring it up via compose, and run functional/contract/perf/a11y/data-quality suites against it.

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

## 12. Roadmap

The full phased plan lives in conversational notes; the abbreviated public form:

| Phase | Goal | Status |
|---|---|---|
| 0 | testing-system skeleton (uv, pytest, ruff, CI) | **Done** |
| 1 | Test strategy + risk register | **In progress** |
| 2 | golf-web-app JSON API + OpenAPI spec | Planned |
| 3 | Playwright user journeys (functional) | Planned |
| 4 | Schemathesis contract tests | Planned |
| 5 | a11y (axe) + perf (k6) budgets in CI | Planned |
| 6 | Great Expectations on data | Planned |
| 7 | golf-web-app AI feature (natural-language booking) | Planned |
| 8 | AI evaluation harness | Planned |
| 9 | Risk-prioritisation agent (PR diff → ranked test plan) | Planned |
| 10 | Triage agent (CI failure clustering) | Planned |
| 11 | Prometheus + Grafana observability stack | Planned |
| 12 | Exploratory testing agent + tests of agents | Planned |

## Appendix A: Glossary

- **SUT** — system under test. Here: `golf-web-app`.
- **Harness** — assurance code that targets the SUT. Here: `testing-system`.
- **Service boundary** — an interface where one component's responsibility ends and another's begins. We assert at boundaries because that's where contracts live.
- **LLM-judge** — an LLM prompted to score another model's output against a rubric. Used in `ai_evaluation/` where deterministic asserts don't fit.
- **Golden set** — a curated input/expected-output dataset used to evaluate models against a known baseline.
