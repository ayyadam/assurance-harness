# AI evaluation harness

Evaluates the golf-web-app booking assistant's natural-language understanding by replaying a labelled golden set of requests through the SUT's live API endpoint (**black-box**) and scoring the returned `BookingIntent` against ground truth.

This is phase 8 of the assurance roadmap. It complements — not replaces — the deterministic stub gate that runs in per-PR CI: the stub keeps the gate fast and reproducible; this harness measures the *real model* on quality, latency and safety, off the per-PR path.

## Why black-box

The eval calls the SUT's `POST /api/v1/booking-assistant` endpoint exactly like a client would. Same prompt, same JSON schema, same coercion, same auth, same matcher. No SUT logic is duplicated into the harness, so the eval can't drift from what the feature actually does. To compare models, the harness reconfigures the SUT to run each one in turn.

## Quick start

The eval is **local on-demand** — it needs a real Ollama-backed SUT and is not run in hosted CI.

```bash
# 1. Bring up the SUT pointed at Ollama on your host. The harness creates a
#    docker-compose.override.yml in ../golf-web-app with the right env vars.
#    Or do it once manually; the orchestrator below handles it per model.

# 2. Compare a list of models (orchestrator reconfigures the SUT per model)
uv run python -m ai_evaluation.run --models "qwen3:8b-fp16,qwen3.6:27b-q4_K_M"

# 3. Single-model run against whatever the SUT is currently running
uv run python -m ai_evaluation.run --model-label qwen3:8b-fp16

# 4. With the LLM-judge tier (holistic + fuzzy). Default judge is
#    qwen2.5:32b-instruct-q4_K_M. Adds ~10 minutes to a 5-model run.
uv run python -m ai_evaluation.run --models "..." --with-judge

# 5. Re-score the cached responses after editing the golden set (no model re-run).
#    Cached judge results are automatically rehydrated if present.
uv run python -m ai_evaluation.run --score-only
```

Reports land in [`reports/`](reports/):
- `report.md` — human-readable summary, per-category accuracy, failure list.
- `report.json` — full structured results.
- `raw_responses.json` — every model's raw response per case, captured at run time. Re-scoring against an edited golden set reads this cache, so refining expected values is free (no model calls).

## Golden set ([`golden_set.yaml`](golden_set.yaml))

Labelled cases — what the structured `BookingIntent` *should* be for each free-text input. The schema is documented at the top of the file. Key points:

- **Relative dates are specs resolved at run time** (`today`, `tomorrow`, `+N`, `next:<weekday>`, `next-week:<weekday>`, `explicit:YYYY-MM-DD`) so the eval is correct whatever day it's run. Host and SUT share a clock, so the model's `date.today()` matches the resolver's.
- **`next:<weekday>` vs `next-week:<weekday>`** — *"this Saturday"* is `next:saturday` (the soonest matching weekday); *"next Saturday"* is `next-week:saturday` (one further week). Matches UK colloquial usage.
- **`period` and time-window are orthogonal axes.** A member who says *"Saturday from 9am"* gets `period=any` and `not_before=09:00`; the time bound carries the constraint. Inferring `period=morning` from `from 9am` would silently hide afternoon slots in the matcher (an F-007 / F-008 class defect). The grader holds that line.
- **Adversarial / robustness** cases carry `expected: {safety: harmless}` and are graded on no-5xx + in-schema + value clamping — *not* field equality. There is no single correct intent for *"delete the database"*; staying safe is the point.

## Grading (v1: deterministic + LLM-judge)

Each case is scored on one of three rubrics, picked from its golden-set shape:

- **Accuracy** (default) — exact equality on `date` (after resolving the date spec), `period`, `group_size`, normalised `players`, `not_before`, `not_after`.
- **Safety** (`expected: {safety: harmless}`) — for adversarial / robustness cases: status < 500, in-schema intent, `group_size` clamped to 1..4. A clean 422 also counts as safe.
- **Fuzzy** (`judge_only: true` + `rubric`) — for cases where exact field equality is too strict (e.g. *"sometime this weekend"* admits Sat **or** Sun). The LLM-judge reads the rubric and the model's response and rules pass/fail with a written rationale.

Latency is wall-clock per case, warm (a throwaway call pre-loads the model before timing).

### LLM-judge tier

Two judge calls per case, opt-in via `--with-judge`:

- **Holistic** (every case) — 0..10 reasonableness score with a written rationale. A second perspective on the deterministic 0/1: catches things deterministic can't see, like over-constraint or unreasonable defaults.
- **Fuzzy** (cases marked `judge_only: true`) — pass/fail against the case's rubric.

The judge runs on its own Ollama model (default `qwen2.5:32b-instruct-q4_K_M`, configurable via `--judge-model`). A different family from the leading models under test reduces same-model self-judging bias. Judge outputs are cached in `reports/judge_cache.json`, so re-rendering the report after a small change doesn't re-invoke the judge.

## Architecture

```
ai_evaluation/
├── evaluator.py        # date-spec resolver, SUT client, field/safety scoring
├── judge.py            # LLM-judge tier (holistic + fuzzy) via Ollama
├── run.py              # CLI: single / compare / --score-only / --with-judge
├── golden_set.yaml     # ground truth
└── reports/            # committed evidence artefacts (md + json + raw + judge cache)
```

## Roadmap (this harness)

- [x] Deterministic field scoring across a labelled golden set
- [x] Multi-model orchestration + per-category + latency
- [x] Raw-response cache → free re-scoring after golden-set edits
- [x] LLM-judge tier for fuzzy cases + holistic reasonableness
- [ ] Periodic / scheduled runs and a quality-bar gate
