# testing-system

Assurance harness targeting [golf-web-app](https://github.com/ayyadam/golf-web-app) — a portfolio demonstration of modern, automation-led quality engineering for the Digital Assurance Engineer role.

## Status

Strategy and risk register in place; the JSON API contract layer (Schemathesis) and the UI/E2E functional layer (Playwright) are live in CI. Subsequent phases extend the test layers described in the strategy.

- [`docs/test-strategy.md`](docs/test-strategy.md) — how we assure golf-web-app, with rationale and findings to date
- [`docs/risk-register.md`](docs/risk-register.md) — risks tracked and what mitigates each one

## Stack

- **Python 3.12**, managed with [uv](https://docs.astral.sh/uv/)
- **pytest** as the test runner, with JUnit + HTML reporting
- **Schemathesis** for property-based API contract tests
- **Playwright** for UI / E2E functional tests
- **axe-core** (axe-playwright-python) for WCAG 2.1 A/AA accessibility checks
- **ruff** for lint + format
- **GitHub Actions** for CI

## Quick start

```bash
# Install everything (uv creates and manages the venv)
uv sync --dev

# Run the test suite
uv run pytest

# Lint and format check
uv run ruff check .
uv run ruff format --check .
```

## Layout

Grows phase by phase. Today:

```
testing-system/
├── pyproject.toml
├── .python-version
├── schemathesis.toml            # contract-test check config
├── docs/
│   ├── test-strategy.md         # phase 1: how we assure
│   └── risk-register.md         # phase 1: what we worry about
├── contract/                    # phase 4: Schemathesis API contract tests
│   ├── conftest.py
│   └── test_api_contract.py
├── functional/                  # phase 3: Playwright UI / E2E journeys
│   ├── conftest.py
│   ├── test_public_pages.py
│   ├── test_member_journey.py
│   └── test_access_control.py
├── nonfunctional/
│   └── accessibility/           # phase 5a: axe-core WCAG 2.1 A/AA sweep
│       ├── conftest.py
│       └── test_accessibility.py
├── tests/                       # tests OF the harness itself
│   └── test_smoke.py
└── .github/workflows/
    └── assurance.yml            # lint + pytest + contract + functional + a11y in CI
```

Contract and functional tests need the SUT running and are excluded from the
default `pytest` run. To run them locally, first bring up the SUT:

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
```

## Related

- **System under test:** [golf-web-app](https://github.com/ayyadam/golf-web-app) — Flask golf-club app, GHCR-published, CI on its own pipeline.
