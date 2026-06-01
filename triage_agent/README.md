# Triage agent

Phase 10 of the assurance roadmap. Clusters failed CI runs by likely root cause, assigns a category (flake / defect / infra / env), and cross-references each cluster against the [risk register](../docs/risk-register.md). Sits in the agentic layer per the [test strategy](../docs/test-strategy.md) Principle 5 — judgement, not a gate. Advisory; the output is a starting point for the on-call reviewer.

## Why it earns its place

A repo accumulates CI failures over time. Some are flakes (R-018-class), some are real defects, some are tooling/infra. A reviewer drowning in red Xs needs help separating signal from noise — and a flake that recurs across multiple PRs is much easier to recognise as a *flake* with the historical picture than from a single failed run viewed in isolation.

The triage agent answers two questions per cluster: *what is this?* (category) and *which register row owns it?* (R-ID cross-reference). The first guides the reviewer to the right action (rerun vs investigate); the second ties the failure back to the mitigation row that should be holding the line — so a cluster of R-018 failures is a signal that R-018's mitigation isn't fully working.

## Design

```
triage_agent/
├── fetcher.py    # gh CLI wrappers: list_failed_runs, fetch_failed_log (cached)
├── parser.py     # extract Failure records from log dumps:
│                 #   pytest FAILED summary lines (test failures)
│                 #   ##[error]Process completed with exit code (step failures)
├── cluster.py    # heuristic group by (test path, test name, error class)
│                 # LLM categorise + R-ID xref per cluster
├── render.py     # markdown
├── run.py        # CLI
└── reports/      # committed evidence (report.md, report.json)
    └── raw/      # gitignored — cached log dumps
```

Decisions worth calling out:

- **Two failure shapes.** The harness produces both **pytest** test failures (via Playwright/Schemathesis) and **step** failures (via ruff, k6, docker compose). The parser handles both: pytest summary lines first; if none are found, fall back to `##[error]Process completed with exit code N` markers with the preceding meaningful output line as the error excerpt.
- **Cached raw logs.** `gh run view --log-failed` is slow and quota-bounded. The first fetch caches under `reports/raw/<run_id>.log`; subsequent runs reuse the cache. Raw logs are gitignored — they can contain transient secrets in env dumps.
- **Heuristic spine, LLM judgement.** Heuristic clustering by `(test path, test name, error class)` is deterministic and almost always correct (same shape = same cause). The LLM handles the parts that need judgement: which category, which register R-ID, what rationale, what action. The register is fed to the LLM as a closed-vocabulary enum for `candidate_risk_id` — the model can't invent a risk ID, only pick one that exists (or `null`).
- **No automatic merging across signatures.** Two clusters with the same candidate R-ID but different test names (e.g. both R-018 flakes on two different functional tests) stay separate. The summary table makes the cross-cluster pattern visible without losing the per-signature detail.

## Quick start

The agent is **local on-demand** — needs `gh` authenticated to the repo and a local Ollama runtime.

```bash
# Default: scan ayyadam/testing-system for the last 30 days of failures
uv run python -m triage_agent.run

# Different repo / window
uv run python -m triage_agent.run --repo ayyadam/golf-web-app --since-days 7

# Skip the LLM categorisation — heuristic clusters only
uv run python -m triage_agent.run --no-llm

# Print to stdout without writing the report files
uv run python -m triage_agent.run --no-write
```

Outputs (under [`reports/`](reports/)):

- `report.md` — human-readable triage with a summary table + per-cluster sections
- `report.json` — structured: clusters, members, category, R-ID, rationale, action

## Evidence: real failures in this repo's last 30 days

The committed [`reports/report.md`](reports/report.md) is the agent run against `ayyadam/testing-system` on 2026-06-01. Five failed runs in the window, clustered into five groups:

| # | Signature | R-ID | What the agent saw |
|---|---|---|---|
| 1 | `test_assistant_interprets_request_and_books_a_slot` → `TimeoutError` | **R-018** (flake) | Functional flake on the booking-confirm flow — same root cause as R-018, recurrence after the fix (the 30s `wait_for_url` was still exceeded on run #31). |
| 2 | `Lint (ruff)::ruff format check` → `<step-failure>` | none | Two files needed reformatting on the first push of phase 8. Pre-push hygiene, not a register risk. |
| 3 | `test_member_books_a_tee_time` → `AssertionError` | **R-018** (flake) | Same root cause as cluster #1 (URL assertion after booking confirm) on a *different* test, on a *much earlier* run (#18, 2026-05-28). |
| 4 | `Performance (k6)::Run k6 load test` → `<step-failure>` | **R-007** (defect) | k6 threshold breach on `http_req_duration{endpoint:tee-times}` — exactly the N+1 query later fixed under F-005. |
| 5 | `Contract Tests (Schemathesis)::Run contract tests` → `<step-failure>` | **R-006** (defect) | Schemathesis contract failure — the cluster maps to the original five spec-vs-behaviour mismatches later fixed under F-003. |

The agent caught one genuinely useful historical finding I would have missed otherwise — **the R-018 flake pattern was present on run #18 (2026-05-28), not just on PRs #11 and #12**. R-018 was retroactively logged after the second occurrence on PR #12, but the agent's cluster view shows it was actually the third recurrence; the original is earlier than the two recent ones that triggered the investigation. That changes the timeline: R-018 isn't a recent regression, it's a standing flake the bar got raised on.

## Known limits

- **No automatic cross-cluster merging by R-ID.** Two R-018 clusters with different test names stay separate. The summary table makes the pattern visible; programmatic merging would lose information (which test was affected when).
- **Single-occurrence "clusters" are common in this dataset.** With 5 failures across 5 distinct signatures, every cluster has exactly 1 member. A repo with higher CI volume would show real grouping. The agent's value scales with failure volume.
- **The agent cannot read traces / screenshots.** Playwright `--tracing=retain-on-failure` artefacts are uploaded by CI but the triage agent only sees the textual log. Real flake diagnosis (e.g. "the dashboard was 502ing, not just slow") needs the trace artefact — out of scope for v1.
- **Categorisation is judgement.** The agent labelled the ruff lint failure as `defect` even though it's really "developer forgot to format" — the available category set (flake/defect/infra/env) doesn't fit it cleanly. A future revision could add `tooling` or `developer-error` categories if the dataset grows.

## v1 v2 — golden-set evaluation tier

The agent is now scored against a labelled golden set on every change. [`golden_set.yaml`](golden_set.yaml) records, per known cluster signature, the (category, R-ID) a reviewer would assign after looking at the failure in context. The evaluator (`triage_agent.eval`) reads the agent's cached `reports/report.json` and reports per-axis accuracy plus a combined both-right score — deterministic, no LLM in the scoring path.

Mirrors `risk_agent.eval` in pattern: cheap re-scoring after a golden-set edit; `--refresh` to re-run the agent against live `gh` data before scoring.

```bash
uv run python -m triage_agent.eval           # score against cached report.json
uv run python -m triage_agent.eval --refresh # re-fetch + re-cluster + re-categorise first
```

### Baseline (v1 v1 agent, five clusters)

Reported in [`reports/eval-report.md`](reports/eval-report.md):

| Metric | Value |
|---|---|
| Cases | 5 |
| Clusters found in report | 5 / 5 |
| **Category accuracy** | **1.000** (5/5) |
| **R-ID accuracy** | **1.000** (5/5) |
| **Combined (both right)** | **1.000** (5/5) |

5/5 on each axis. The agent correctly categorised every cluster and picked the right register R-ID (or correctly returned `null` for the ruff-format failure). The baseline is the deliverable — any future regression below 5/5 is now immediately visible, and any agent change (prompt, model, schema) is measurable against this.

### Honest caveats on the baseline

A 100% result with five cases needs context:

- **The dataset is small.** Five clusters across five distinct signatures means each is its own cluster of one. A repo with higher CI volume would surface real cluster sizes and stress the heuristic more.
- **All cases are from one repo.** `golf-web-app` CI failures aren't in the set. Cross-repo triage would change the distribution.
- **The "hardest" call in this set is the ruff lint mapping.** None of `{flake, defect, infra, env}` fits "developer forgot to run ruff before push" cleanly; both the golden set and the agent pick `defect` as the closest available label. That's a category-set limit, not an agent strength.
- **The triage problem is more constrained than risk-prioritisation.** Each cluster is one specific failure signature with one obvious category and one obvious R-ID (if any). The risk_agent's open-ended N-of-18 ranking is genuinely harder, which is why the risk_agent eval baseline sits at F1 0.526 while this one sits at 1.000. Same evaluation discipline, different problem shape.

These caveats limit how strong the *single number* is — but the **process** stands: a labelled set in the repo, a scorer in the repo, a numeric baseline future changes are measured against.

## Roadmap (this agent)

- [x] v1 v1: heuristic clustering + LLM categorisation + R-ID xref, evidence on this repo's last 30 days
- [x] v1 v2: golden-set evaluation tier with deterministic scorer (5/5 baseline)
- [ ] v1 v3 candidates: grow the dataset (cross-repo failures); add `tooling` / `developer-error` to the category vocabulary if the ruff-class miss recurs
- [ ] Pull Playwright traces into the diagnosis (LLM-judged failure mode beyond the textual log)
- [ ] Cross-repo triage (`golf-web-app` + `testing-system` together)
