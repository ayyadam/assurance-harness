# testing-system

Assurance harness targeting [golf-web-app](https://github.com/ayyadam/golf-web-app) — a portfolio demonstration of modern, automation-led quality engineering for the Digital Assurance Engineer role.

## Status

**Phase 1** — strategy and risk register in place. Subsequent phases extend the test layers described in the strategy.

- [`docs/test-strategy.md`](docs/test-strategy.md) — how we assure golf-web-app, with rationale and findings to date
- [`docs/risk-register.md`](docs/risk-register.md) — risks tracked and what mitigates each one

## Stack

- **Python 3.12**, managed with [uv](https://docs.astral.sh/uv/)
- **pytest** as the test runner, with JUnit + HTML reporting
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
├── tests/                       # tests OF the harness itself
│   └── test_smoke.py
└── .github/workflows/
    └── assurance.yml            # lint + pytest + contract in CI
```

Contract tests need the SUT running and are excluded from the default
`pytest` run. To run them locally:

```bash
cd ../golf-web-app && docker compose up -d && docker compose exec web python seed.py
cd ../testing-system && uv run pytest contract/
```

## Related

- **System under test:** [golf-web-app](https://github.com/ayyadam/golf-web-app) — Flask golf-club app, GHCR-published, CI on its own pipeline.
