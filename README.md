# testing-system

Assurance harness targeting [golf-web-app](https://github.com/ayyadam/golf-web-app) — a portfolio demonstration of modern, automation-led quality engineering for the Digital Assurance Engineer role.

## Status

**Phase 0** — skeleton and CI. The harness collects, runs, and publishes reports. Subsequent phases add real assurance work; see `docs/test-strategy.md` (phase 1).

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
├── tests/                       # tests OF the harness itself
│   └── test_smoke.py
└── .github/workflows/
    └── assurance.yml            # lint + pytest in CI
```

## Related

- **System under test:** [golf-web-app](https://github.com/ayyadam/golf-web-app) — Flask golf-club app, GHCR-published, CI on its own pipeline.
