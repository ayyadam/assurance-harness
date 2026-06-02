# Agent regression suite (phase 12 v2 v2)

Treats `risk_agent` and `triage_agent` as software under test. The eval
tiers (`risk_agent.eval`, `triage_agent.eval`, `explore_agent.eval`) measure
**accuracy** against ground truth — does the agent get the right answer.
This suite measures **stability under LLM jitter** — does the agent give
the same answer when run multiple times against the same input, and do its
closed-vocabulary contracts hold every time.

## What is asserted

For each cached fixture (a frozen PR diff for `risk_agent`, a synthetic
cluster for `triage_agent`), the agent is invoked N times (currently N=3).
Two layers of assertion:

**Hard invariants** (must hold every run):

- **Schema validity** — the structured output decodes and has the expected
  shape (summary, ranked_risks, exploratory_probes for risk_agent;
  category, candidate_risk_id, rationale, suggested_action for triage).
- **Closed vocabulary** — every emitted R-ID exists in the live register;
  every emitted category is in the closed enum; relevance is always in
  {2, 3} (the v2 v1 prompt change forbade 0/1).

**Soft invariants** (must hold ≥ 66% of runs):

- **Top-result stability** — the highest-ranked R-ID for risk_agent, the
  category and R-ID for triage_agent — should agree across runs at least
  2/3 of the time. A lower stability is a regression signal worth
  investigating.
- **Expected-top hit-rate** — the golden-set's expected top R-ID should
  appear *somewhere* in the ranking in ≥ 66% of runs.

**Stable-divergent warning** (does not fail the test):

A case where the agent's answer is *internally stable* (high
agreement across runs) but *disagrees with the golden set* on the top-1
result. The hard invariants still hold — schema and closed-vocab are
intact — so the test passes. But because high stability rules out
"the model is just jittery", a stable disagreement is a real signal:
either the prompt is producing a consistently wrong inference, or the
golden set under-rates a defensible reading. Either way, it deserves
investigation rather than being buried in a "tests passed" headline.

The warning is emitted via `warnings.warn(StableDivergentWarning(...))`
so it shows up in pytest output as a `WARNING` line; the renderer
surfaces it in the summary table (`⚠ stable-divergent`) and in a
dedicated section. See [`_runner.py`](_runner.py) for the
`expected_match_rate` helper and `StableDivergentWarning` class.

## How to run

The suite is gated on the `RUN_AGENT_REGRESSION` env var so it does not
slow the default `pytest` run or the CI gate:

```bash
RUN_AGENT_REGRESSION=1 uv run pytest tests/agents/ -v
uv run python tests/agents/render_report.py
```

Total runtime: ~3 minutes local. Each test case invokes the agent N=3
times against the chosen Ollama model (default `qwen2.5:32b-instruct-q4_K_M`).

## Layout

```
tests/agents/
├── README.md                           — this file
├── conftest.py                         — env-var gate
├── _runner.py                          — run_n_times + jitter helpers
├── fixtures/
│   ├── risk_pr-7.diff                  — cached gh pr diff
│   └── risk_pr-12.diff
├── test_risk_agent_invariants.py       — 2 cases × N runs
├── test_triage_agent_invariants.py     — 2 cases × N runs
├── render_report.py                    — markdown from the JSON dumps
└── reports/                            — committed evidence
    ├── regression-report.md            — human-readable summary
    ├── regression-report-risk.json
    └── regression-report-triage.json
```

## What v2 v2 measures that v2 v1 (eval) does not

- **Eval (v2 v1)** — single run against a golden case; asks "is the agent's
  answer right?"
- **Regression (v2 v2)** — N runs against the same input; asks "is the
  agent stable AND does the closed-vocab contract hold?"

A single right answer hides flapping. A stable wrong answer is a different
problem from a stably-right one. Both numbers are needed.

## Notable findings from the baseline run

- **`risk_agent` on PR #12 (F-008) — stable-divergent**. The agent ranks
  R-002 (concurrent bookings) as the top risk in 3/3 runs; the golden
  set expects R-011 (AI booking accuracy). Top-match rate vs golden:
  0%. Hard invariants held — this is the warning case the v2 v2 suite
  is built to surface.
  - Investigation traced the cause: the agent ranks R-002, R-011, R-012,
    R-018 all at relevance 3 (tied), and `risk_agent.agent` breaks ties
    by ascending R-ID. R-002 wins because of its alphabetical position,
    not because the model puts it above R-011.
  - Underneath the sort artefact is a real model error: PR #12 doesn't
    touch the booking *write* path, so R-002 (about concurrent booking
    races) shouldn't be in the set at all. The model is over-pulling
    "diff touches booking-adjacent code" → "concurrency at risk".
  - Model-swap evidence: same R-002 over-pull on `qwen2.5:14b` with
    near-identical rationale. Not capability-bound; the fix space is
    prompt or register framing. Tracked as a phase 9 v3 follow-up in
    the [sub-roadmap](../../docs/test-strategy.md#phase-12-sub-roadmap).
- **`triage_agent` is 100% stable** on both fixtures (category and R-ID
  identical across all 3 runs). The closed-vocabulary enum on R-ID is
  holding — no inventions, no flapping.
- **Schema validity: 12/12 runs. Closed vocabulary: 12/12.** The Ollama
  `format=` enforcement is doing its job; this baseline gives us a
  measurable backstop if it ever stops.

See [`reports/regression-report.md`](reports/regression-report.md) for the
full table + per-run breakdown including the dedicated stable-divergent
section.
