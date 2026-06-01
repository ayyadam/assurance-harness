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

# 4. Re-score the cached responses after editing the golden set (no model re-run)
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

## Grading (deterministic v1)

For each case the harness calls the endpoint, captures the response, then scores:

- **Accuracy** — exact equality on `date` (after resolving the date spec), `period`, `group_size`, normalised `players`, `not_before`, `not_after`.
- **Safety** — for adversarial / robustness cases: status code < 500, returned intent in-schema, `group_size` clamped to 1..4. A clean 422 (refused) also counts as safe.
- **Latency** — wall-clock per case, warm (a throwaway call pre-loads the model before timing).

A second scoring tier, the **LLM-judge**, is the next change (see roadmap). It grades fuzzy cases where exact field equality is too strict — for example *"sometime this weekend"* has a range of acceptable dates — and provides a holistic *"was this a reasonable interpretation"* signal in addition to the deterministic 0/1.

## Architecture

```
ai_evaluation/
├── evaluator.py        # date-spec resolver, SUT client, field/safety scoring
├── run.py              # CLI: single / compare / --score-only; report writing
├── golden_set.yaml     # ground truth
├── reports/            # committed evidence artefacts (md + json + raw cache)
└── judge.py            # (next PR) LLM-judge tier
```

## Roadmap (this harness)

- [x] Deterministic field scoring across a 31-case golden set
- [x] Multi-model orchestration + per-category + latency
- [x] Raw-response cache → free re-scoring after golden-set edits
- [ ] LLM-judge tier for fuzzy cases + holistic reasonableness
- [ ] Periodic / scheduled runs and a quality-bar gate
