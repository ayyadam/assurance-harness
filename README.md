# testing-system

Assurance harness targeting [golf-web-app](https://github.com/ayyadam/golf-web-app) — a portfolio demonstration of modern, automation-led quality engineering for the Digital Assurance Engineer role.

## Status

Strategy and risk register are the source of truth — [`docs/test-strategy.md`](docs/test-strategy.md) tracks layer-by-layer status and findings, and [`docs/risk-register.md`](docs/risk-register.md) tracks the risks and mitigations.

Currently in place across the two repos:

- **Per-PR CI gates (`testing-system/.github/workflows/assurance.yml`):** lint (ruff), harness pytest, contract (Schemathesis), functional (Playwright), accessibility (axe-core), performance (k6), data quality (pandera) — every gate runs against an ephemeral SUT brought up from `golf-web-app`'s source.
- **Local on-demand layers:** AI evaluation harness ([`ai_evaluation/`](ai_evaluation/README.md), phase 8), risk-prioritisation agent ([`risk_agent/`](risk_agent/README.md), phase 9), and triage agent ([`triage_agent/`](triage_agent/README.md), phase 10). All three use a local Ollama runtime so the per-PR path stays fast and reproducible; their evidence artefacts are committed under each module's `reports/` dir.
- **Documented findings:** F-001 through F-009 captured in the strategy with diagnosis, fix, and generalisation.

## Stack

- **Python 3.12**, managed with [uv](https://docs.astral.sh/uv/)
- **pytest** as the test runner, with JUnit + HTML reporting
- **Schemathesis** for property-based API contract tests
- **Playwright** for UI / E2E functional tests
- **axe-core** (axe-playwright-python) for WCAG 2.1 A/AA accessibility checks
- **k6** for performance budgets (thresholds-as-code)
- **pandera** for data-quality checks on the live database
- **Ollama** for the AI evaluation harness and risk-prioritisation agent (local on-demand only — not in CI)
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
testing-system/
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
├── nonfunctional/
│   ├── accessibility/              # phase 5a: axe-core WCAG 2.1 A/AA sweep
│   │   ├── conftest.py
│   │   └── test_accessibility.py
│   ├── performance/                # phase 5b: k6 thresholds-as-code
│   │   └── api_load.js
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
│   ├── render.py + run.py          # CLI + markdown
│   ├── golden_set.yaml             # v2 v2: expected ranks per historic PR
│   ├── eval.py                     # v2 v2: deterministic scorer (precision/recall/F1)
│   └── reports/                    # committed evidence (per-PR + eval-report)
├── triage_agent/                   # phase 10: cluster failed CI runs by root cause
│   ├── fetcher.py                  # gh CLI wrappers (cached log dumps)
│   ├── parser.py                   # pytest + step-failure extraction
│   ├── cluster.py                  # heuristic group + LLM category + R-ID xref
│   ├── render.py + run.py          # CLI + markdown
│   ├── golden_set.yaml             # v1 v2: expected (category, R-ID) per cluster
│   ├── eval.py                     # v1 v2: deterministic scorer
│   └── reports/                    # committed evidence (report.md + eval-report.md)
├── tests/                          # tests OF the harness itself
│   └── test_smoke.py
└── .github/workflows/
    └── assurance.yml               # the per-PR gates above
```

## Running the suites locally

The contract, functional, accessibility, performance, and data-quality layers need the SUT running. Bring it up first:

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

### Local-on-demand layers (Ollama-backed)

Both phase 8 and phase 9 use a local Ollama runtime — they are deliberately *not* in CI so the per-PR gate stays fast and reproducible, and the model isn't a moving budget on the critical path.

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
```

See [`ai_evaluation/README.md`](ai_evaluation/README.md) and [`risk_agent/README.md`](risk_agent/README.md) for the full design notes and committed evidence.

## Related

- **System under test:** [golf-web-app](https://github.com/ayyadam/golf-web-app) — Flask golf-club app, GHCR-published, CI on its own pipeline.
