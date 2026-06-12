# assurance-harness

Assurance harness targeting [golf-web-app](https://github.com/ayyadam/golf-web-app) — a portfolio demonstration of modern, automation-led quality engineering.

## Status

Strategy and risk register are the source of truth — [`docs/test-strategy.md`](docs/test-strategy.md) tracks layer-by-layer status and findings, and [`docs/risk-register.md`](docs/risk-register.md) tracks the risks and mitigations.

Currently in place across the two repos:

- **Per-PR CI gates (`assurance-harness/.github/workflows/assurance.yml`):** lint (ruff), harness pytest, contract (Schemathesis), functional (Playwright), TypeScript E2E (Playwright/TS — the polyglot [`e2e_ts/`](e2e_ts/README.md) layer, B20), accessibility (axe-core), performance (k6), data quality (pandera), and a shift-left **security** gate — Bandit + CodeQL (SAST), pip-audit (SCA), gitleaks (secrets), OWASP ZAP baseline (DAST) under [`nonfunctional/security/`](nonfunctional/security/README.md) (B1) with ratchet gating. Every gate runs against an ephemeral SUT brought up from `golf-web-app`'s source.
- **Local on-demand agent layers (Ollama-backed):** AI evaluation harness ([`ai_evaluation/`](ai_evaluation/README.md), phase 8), risk-prioritisation agent with a deterministic register pre-filter ([`risk_agent/`](risk_agent/README.md), phase 9 + phase 13), triage agent ([`triage_agent/`](triage_agent/README.md), phase 10), exploratory agent — API + UI surfaces plus spec-aware auth-bypass probing ([`explore_agent/`](explore_agent/README.md), phase 12), and security agent — judges the B1 scanner findings (FP-vs-real + disposition + register R-ID) and reconciles the SCA allowlist ([`security_agent/`](security_agent/README.md), B1c). All five use a local Ollama runtime so the per-PR path stays fast and reproducible; each carries a deterministic golden-set eval tier, and their evidence artefacts are committed under each module's `reports/` dir.
- **Production-style observability:** Prometheus + Grafana stack ([`observability/`](observability/README.md), phase 11) scraping the SUT's `/metrics`; SLO thresholds on the dashboard match the k6 perf gate's pre-merge budget. Closes R-013.
- **Tests of the harness's own agents:** a gated regression suite ([`tests/agents/`](tests/agents/README.md), phase 12 v2 v2 + F-024) running `risk_agent`, `triage_agent`, and the `explore_agent` judge N times against fixed inputs, asserting schema/vocab invariants and stability under LLM jitter — including a non-blinding positive control on the explore judge.
- **Documented findings:** F-001 through F-033 captured in the strategy with diagnosis, fix, and generalisation — including the full security lifecycle (F-029 detect → F-030 judge → F-031 reconcile → F-032 remediate + re-arm → F-033 SARIF-native + secrets).

## Stack

- **Python 3.12**, managed with [uv](https://docs.astral.sh/uv/)
- **pytest** as the test runner, with JUnit + HTML reporting
- **Schemathesis** for property-based API contract tests
- **Playwright** for UI / E2E functional tests
- **TypeScript + Playwright** for a second, polyglot E2E layer ([`e2e_ts/`](e2e_ts/README.md)) — the same journeys in TS, on a Node 22 / npm toolchain (B20)
- **axe-core** (axe-playwright-python) for WCAG 2.1 A/AA accessibility checks
- **k6** for performance budgets (thresholds-as-code)
- **pandera** for data-quality checks on the live database
- **Bandit + CodeQL** (SAST), **pip-audit** (SCA), **gitleaks** (secrets), **OWASP ZAP** (DAST baseline) for the security gate
- **Ollama** for the five agent layers — AI evaluation, risk-prioritisation, triage, exploration, and security triage (local on-demand only — not in CI)
- **ruff** for lint + format
- **GitHub Actions** for CI

## Quick start

```bash
# Install everything (uv creates and manages the venv)
uv sync --dev

# Run the harness's own pytest suite (no SUT needed)
uv run pytest

# Lint and format check
uv run ruff check .
uv run ruff format --check .
```

## Layout

```
assurance-harness/
├── pyproject.toml
├── .python-version
├── schemathesis.toml               # contract-test check config
├── docs/
│   ├── test-strategy.md            # how we assure, layer status, findings to date
│   └── risk-register.md            # risks tracked and their mitigations
├── contract/                       # phase 4: Schemathesis API contract tests
│   ├── conftest.py
│   └── test_api_contract.py
├── functional/                     # phase 3 + 7: Playwright UI / E2E journeys
│   ├── conftest.py                 # Playwright config — see F-009 for expect timeout
│   ├── test_public_pages.py
│   ├── test_member_journey.py
│   ├── test_access_control.py
│   └── test_booking_assistant.py
├── e2e_ts/                         # B20: TypeScript / Playwright E2E (polyglot twin of functional/)
│   ├── package.json                # pinned: Node 22 LTS, exact @playwright/test
│   ├── playwright.config.ts        # baseURL from env, CI retries, gating
│   ├── tsconfig.json
│   ├── fixtures.ts                 # creds, login, memberPage, R-018 scroll shim
│   ├── components/                 # component objects (NavBar — shared nav)
│   ├── pages/                      # page objects (Home, Login, MemberDashboard, Booking)
│   └── tests/                      # member-journey, public-pages, access-control
├── nonfunctional/
│   ├── accessibility/              # phase 5a: axe-core WCAG 2.1 A/AA sweep
│   │   ├── conftest.py
│   │   └── test_accessibility.py
│   ├── performance/                # phase 5b: k6 thresholds-as-code
│   │   └── api_load.js
│   ├── security/                   # B1: shift-left security gate
│   │   ├── scan.py                 # SAST (Bandit) + SCA (pip-audit) + secrets (gitleaks), ratchet gating
│   │   └── sca_allowlist.txt       # accepted CVEs (re-armed to empty after F-032)
│   └── reports/                    # CI-only evidence (a11y + perf), gitignored,
│                                   # uploaded as GitHub Actions artefacts
├── data_quality/                   # phase 6: pandera schemas + invariants
│   ├── conftest.py
│   └── test_data_quality.py
├── ai_evaluation/                  # phase 8: black-box golden-set scoring
│   ├── evaluator.py                # field equality + safety scoring
│   ├── judge.py                    # LLM-judge tier (holistic + fuzzy)
│   ├── run.py                      # CLI: single / compare / --with-judge
│   ├── golden_set.yaml             # ground truth (40 labelled cases)
│   └── reports/                    # committed evidence
├── risk_agent/                     # phase 9: PR diff → ranked test plan
│   ├── register.py                 # parses docs/risk-register.md
│   ├── diff.py                     # gh pr diff / --diff file
│   ├── agent.py                    # Ollama structured-output call
│   ├── prefilter.py                # phase 13: deterministic register pre-filter (path + content)
│   ├── render.py + run.py          # CLI + markdown
│   ├── golden_set.yaml             # expected ranks per historic PR
│   ├── eval.py                     # deterministic scorer (precision/recall/F1)
│   └── reports/                    # committed evidence (per-PR + eval-report)
├── triage_agent/                   # phase 10: cluster failed CI runs by root cause
│   ├── fetcher.py                  # gh CLI wrappers (cached log dumps)
│   ├── parser.py                   # pytest + step-failure extraction
│   ├── cluster.py                  # heuristic group + LLM category + R-ID xref
│   ├── render.py + run.py          # CLI + markdown
│   ├── golden_set.yaml             # v1 v2: expected (category, R-ID) per cluster
│   ├── eval.py                     # v1 v2: deterministic scorer
│   └── reports/                    # committed evidence (report.md + eval-report.md)
├── observability/                  # phase 11: Prometheus + Grafana stack
│   ├── docker-compose.yml          # stack (Prometheus + Grafana)
│   ├── prometheus/prometheus.yml   # scrape config (host.docker.internal:5000)
│   ├── grafana/                    # provisioned datasource + dashboard
│   └── evidence/                   # committed screenshots
├── explore_agent/                  # phase 12: LLM-driven exploration (API + UI)
│   ├── spec.py + probe.py          # v1 v1: API surface — OpenAPI-driven + auth-bypass probing
│   ├── judge.py + render.py + run.py
│   ├── tours.py + ui_probe.py      # v1 v3: UI surface — adaptive Playwright tours (policy)
│   ├── ui_judge.py + ui_run.py
│   ├── eval.py                     # v2 v1: deterministic golden-set scorer
│   └── reports/                    # committed evidence (report.md + ui/report.md + screenshots)
├── security_agent/                 # B1c: judges the B1 security findings
│   ├── findings.py                 # normalise Bandit + pip-audit + gitleaks/any SARIF (SARIF-native)
│   ├── judge.py                    # LLM: verdict + disposition + R-ID xref
│   ├── writeback.py                # F-031: reconcile + propose SCA allowlist diff (--apply)
│   ├── render.py + run.py          # CLI + markdown
│   ├── golden_set.yaml             # expected (verdict, disposition, R-ID) per finding
│   ├── eval.py                     # deterministic scorer
│   └── reports/                    # committed evidence (report + eval + writeback)
├── tests/                          # tests OF the harness itself
│   ├── test_smoke.py
│   ├── test_prefilter.py           # phase 13: risk_agent register pre-filter unit tests
│   ├── test_auth_finding.py        # F-020: explore_agent spec-aware auth finding unit tests
│   └── agents/                     # phase 12 v2 v2 + F-024: agent regression (gated)
│       ├── fixtures/               # cached PR diffs + synthetic clusters
│       ├── _runner.py              # run-N-times harness + jitter metrics
│       ├── test_risk_agent_invariants.py
│       ├── test_triage_agent_invariants.py
│       ├── test_explore_judge_nonblinding.py   # F-024: judge non-blinding positive control
│       ├── render_report.py        # combined markdown from JSON dumps
│       └── reports/                # committed evidence
└── .github/workflows/
    └── assurance.yml               # the per-PR gates above
```

## Running the suites locally

The contract, functional, TypeScript E2E, accessibility, performance, and data-quality layers need the SUT running. Bring it up first:

```bash
cd ../golf-web-app && docker compose up -d && docker compose exec web python seed.py
```

Then, from this repo:

```bash
# API contract tests
uv run pytest contract/

# UI / E2E functional tests (one-time browser download first)
uv run playwright install chromium
uv run pytest functional/

# Accessibility sweep (axe-core, WCAG 2.1 A/AA)
uv run pytest nonfunctional/accessibility/

# Data-quality checks (pandera against the live database)
uv run pytest data_quality/
```

The TypeScript E2E layer ([`e2e_ts/`](e2e_ts/README.md)) uses its own Node toolchain (not uv/pytest):

```bash
cd e2e_ts
npm ci                            # install pinned deps
npx playwright install chromium   # one-time browser download
npm test                          # gating; SUT_BASE_URL overrides the target
```

Performance is run by k6 (not pytest). With k6 installed:

```bash
k6 run nonfunctional/performance/api_load.js
```

Or via Docker, with no local k6 install:

```bash
SUT_BASE_URL=http://host.docker.internal:5000 \
  docker run --rm -i -e SUT_BASE_URL -v "$PWD:/work" -w /work \
  grafana/k6 run nonfunctional/performance/api_load.js
```

The security gate's static scans (SAST + SCA + secrets) need only the SUT *source* checked out as a sibling, not a running SUT:

```bash
# Shift-left security scan (Bandit + pip-audit + gitleaks), ratchet gating
uv run python nonfunctional/security/scan.py --sut ../golf-web-app
```

### Local-on-demand layers (Ollama-backed)

The five agent layers (phases 8, 9, 10, 12 + B1c) use a local Ollama runtime — they are deliberately *not* in CI so the per-PR gate stays fast and reproducible, and the model isn't a moving budget on the critical path.

```bash
# AI evaluation harness — score the booking assistant across a model list
# (assumes the SUT is up and pointed at Ollama; see ai_evaluation/README.md)
uv run python -m ai_evaluation.run --models "qwen3:8b-fp16,qwen3.6:27b-q4_K_M"

# Risk-prioritisation agent — rank risks raised by a PR diff
uv run python -m risk_agent.run --pr 12 --repo ayyadam/golf-web-app

# Risk-prioritisation agent — eval against the golden set
uv run python -m risk_agent.eval                  # score against cached reports
uv run python -m risk_agent.eval --refresh        # re-run agent on each case first

# Triage agent — cluster failed CI runs over a time window
uv run python -m triage_agent.run                                  # default: this repo, last 30 days
uv run python -m triage_agent.run --since-days 7                   # narrower window
uv run python -m triage_agent.run --no-llm                         # heuristic clusters only

# Triage agent — eval against the golden set
uv run python -m triage_agent.eval                                 # score against cached report
uv run python -m triage_agent.eval --refresh                       # re-run the triage agent first

# Exploratory agent — probe every API endpoint with LLM-generated payload variants
# (SUT must be up; see explore_agent/README.md)
uv run python -m explore_agent.run                                 # default model, full LLM run
uv run python -m explore_agent.run --no-llm                        # deterministic empty-body probes only

# Exploratory agent — UI tours via Playwright (adaptive: LLM decides one step at a time, LLM judges per step)
uv run python -m explore_agent.ui_run                              # all tours, headless
uv run python -m explore_agent.ui_run --tour booking-assistant     # single tour
uv run python -m explore_agent.ui_run --headed                     # show the browser

# Exploratory agent — eval against the golden set (API surface)
uv run python -m explore_agent.eval                                # score against cached report
uv run python -m explore_agent.eval --refresh                      # re-run the agent first

# Security agent — judge the B1 scanner findings (verdict + disposition + R-ID)
uv run python -m security_agent.run --refresh                      # re-scan + judge
uv run python -m security_agent.eval                               # score against the golden set
uv run python -m security_agent.writeback                          # reconcile + propose allowlist diff
uv run python -m security_agent.writeback --apply                  # write additions + stale removals

# Agent regression suite (phase 12 v2 v2 + F-024) — runs risk_agent,
# triage_agent, and the explore_agent judge N times against fixed inputs;
# asserts schema/vocab invariants, top-result stability under LLM jitter,
# and a non-blinding positive control on the explore judge. ~3 min local.
RUN_AGENT_REGRESSION=1 uv run pytest tests/agents/ -v
uv run python tests/agents/render_report.py                        # refresh the markdown report (risk + triage)
```

### Observability stack

Local Prometheus + Grafana scraping the SUT's `/metrics` — see [`observability/README.md`](observability/README.md). Bring up the SUT first, then:

```bash
cd observability && docker compose up -d
# Grafana:    http://localhost:3000   (anonymous viewer enabled)
# Dashboard:  http://localhost:3000/d/sut-overview
# Prometheus: http://localhost:9090
```

See each module's README — [`ai_evaluation/`](ai_evaluation/README.md), [`risk_agent/`](risk_agent/README.md), [`triage_agent/`](triage_agent/README.md), [`explore_agent/`](explore_agent/README.md), [`security_agent/`](security_agent/README.md), [`nonfunctional/security/`](nonfunctional/security/README.md), [`observability/`](observability/README.md) — for the full design notes and committed evidence.

## Related

- **System under test:** [golf-web-app](https://github.com/ayyadam/golf-web-app) — Flask golf-club app, GHCR-published, CI on its own pipeline.
