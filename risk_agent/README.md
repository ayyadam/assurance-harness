# Risk-prioritisation agent

Phase 9 of the assurance roadmap. Given a pull-request diff and the project's [risk register](../docs/risk-register.md), the agent produces a ranked test plan — which risks are most plausibly raised by this change, which test layer already covers each, where the coverage gaps are, and a short list of exploratory probes a human reviewer should consider.

Sits in the agentic layer per the [test strategy](../docs/test-strategy.md) Principle 5: *determinism for gates, agents for judgement*. The agent is **advisory**; it is not a CI gate. Its output is committed under [`reports/`](reports/) as evidence and feeds the reviewer's decision-making.

## Why it earns its place

Risk-based prioritisation is the strategy's first principle, but in practice the link from "a diff lands on a PR" to "which rows in the register apply, and which layers already cover them" is done by hand. The agent automates that link, citing register IDs verbatim so its output can be checked against the source of truth.

The pay-off is twofold:

- **Faster reviewer focus.** The plan ranks the top-of-mind risks for the diff and tells the reviewer which automated layer already runs against each — so the human spends their time on the residual judgement calls (exploratory probes, gap risks) rather than re-deriving the obvious.
- **Coverage-gap surfacing.** When a diff plausibly raises a register-*open* risk with no current layer, the agent flags it. That is a class of finding deterministic gates cannot produce — they only fail on what they already test.

## Design

Black-box advisory agent over local Ollama:

```
risk_agent/
├── register.py   # parses docs/risk-register.md → list[Risk]
├── diff.py       # `gh pr diff` or --diff file → DiffBundle (with hunk-aware truncation)
├── agent.py      # Ollama structured-output call; JSON schema with risk-ID enum
├── render.py     # AgentResult → markdown
├── run.py        # CLI
└── reports/      # committed evidence (markdown + JSON per PR)
```

Decisions worth calling out:

- **Register is parsed, not embedded.** The agent reads the register file at run time, so when a risk row changes status or mitigation, the agent's view changes with it.
- **Risk IDs are a schema enum.** The Ollama structured-output schema restricts `ranked_risks[].id` to the parsed register's IDs. The model cannot invent or rename a risk; if it tries, the call fails.
- **Diff truncation is hunk-aware.** Diffs over the line cap are cut at the last `diff --git` header before the cap so the model never sees half a hunk. Truncation is announced in the rendered output.
- **`covered_by` is judged from the register's mitigation column, not by the model's opinion of coverage adequacy.** The system prompt ties `is_gap=true` to `status=open` in the register. This boundary is what keeps the agent from inventing gaps in already-mitigated areas. (See *known failure modes* below — it still slips occasionally.)

## Model

Default: `qwen2.5:32b-instruct-q4_K_M` — the same model that passes structured-output reliably in the phase-8 LLM-judge tier. The leading qwen3.6:27b candidate from phase 8 was tried first and rejected here: with `think=False` it emits YAML when given a complex JSON schema. The 32B qwen2.5 instruct model honours the schema cleanly. Override via `--model` if you want to compare.

## Quick start

The agent is **local on-demand** — Ollama on the host, run from the testing-system venv.

```bash
# Against a GitHub PR (gh-authenticated)
uv run python -m risk_agent.run --pr 12 --repo ayyadam/golf-web-app

# Against a saved diff file
uv run python -m risk_agent.run --diff /tmp/my-pr.diff

# Different model / different repo
uv run python -m risk_agent.run --pr 8 --repo ayyadam/golf-web-app --model qwen3:8b-fp16

# Print markdown without writing reports/
uv run python -m risk_agent.run --pr 7 --repo ayyadam/golf-web-app --no-write
```

Outputs:

- `risk_agent/reports/<label>-plan.md` — human-readable plan (the evidence artefact)
- `risk_agent/reports/<label>-plan.json` — the structured agent result

## Evidence

[`reports/`](reports/) contains four committed runs against the SUT's recent merged PRs:

| Report | PR | Headline risk the agent ranked #1 | Was that correct? |
|---|---|---|---|
| [`pr-12-plan.md`](reports/pr-12-plan.md) | golf-web-app #12 (F-008 time-window) | **R-011** (AI booking) | Yes |
| [`pr-11-plan.md`](reports/pr-11-plan.md) | golf-web-app #11 (F-007 slot truncation) | **R-011** (AI booking) | Yes |
| [`pr-8-plan.md`](reports/pr-8-plan.md)  | golf-web-app #8 (N+1 fix) | **R-007** (performance) | Yes |
| [`pr-7-plan.md`](reports/pr-7-plan.md)  | golf-web-app #7 (a11y contrast) | **R-008** (accessibility) | Yes |

On four diverse PRs across four different test layers, the agent flags 2–4 register risks each (down from 6 in v1's padded top-6 lists), with `covered_by` and `is_gap` deterministically derived from the register row (not the model). The reviewer reads top-down and stops where the value ends.

One probe the agent suggested on PR #12 that was *not* in the manual exploration: *"setting `not_before` after `not_after` to ensure proper error handling"*. The inverted-window case is now a candidate for a real golden-set entry. The agent surfaced a real coverage idea.

## v2 v1 — what changed and why

v1 ran four demo PRs and exposed four observable failure modes. v2 v1 keeps the same architecture (Ollama structured output, register-driven schema, advisory only) and retires three of them through post-processing:

| Failure mode (v1) | Status in v2 v1 | How |
|---|---|---|
| **Lower-rank noise** — ranks #4–6 stretched on every PR | **Substantially reduced** | Schema now requires a `relevance` integer constrained to `{2: "plausible", 3: "direct"}`. Speculative entries (the old #4–6 tail) literally can't be emitted; the model self-filters. Average entries per PR dropped from 6 → 3 |
| **`is_gap` mis-classification** — partially-mitigated risks sometimes flagged GAP | **Retired (structural)** | `is_gap` is no longer a model output. It's computed at register parse time from the row's `status` (true iff `status == "open"`). |
| **`covered_by` malformed strings** — PR #8 R-017 emitted an action-version list, not a layer | **Retired (structural)** | `covered_by` is no longer a model output. It's derived from the register's mitigation column at parse time via a closed-vocabulary keyword map (e.g. `"ai_evaluation/"`, `"Schemathesis contract suite"`, `"k6 performance gate"`). Unclassified rows return a visible `"see register (no canonical layer detected)"` rather than a malformed string. |
| **R-002 over-pull on booking PRs** — flagged on any booking-area change | **Open** | The model still over-claims R-002 as `direct` on PR #12 even though the diff doesn't change concurrency semantics. This is a judgement issue inside the relevance scoring, not a structural one; addressing it needs a PR golden set with expected ranks so we can measure regression (v2 v2). |

The model still drives summary, rationale, action, and exploratory probes — the parts where its judgement actually earns its place. The structural fields (`covered_by`, `is_gap`) are deterministic. Failure modes that *can* be retired by post-processing have been.

### Re-run results

The same four historic PRs (overwritten reports under [`reports/`](reports/)):

| Report | PR | Ranks (v1 → v2 v1) | Top entry | `is_gap` correctness |
|---|---|---|---|---|
| [`pr-12-plan.md`](reports/pr-12-plan.md) | golf-web-app #12 (F-008) | 6 → 4 | R-002 (direct), R-011 (direct) both at relevance 3 | All 4 correct |
| [`pr-11-plan.md`](reports/pr-11-plan.md) | golf-web-app #11 (F-007) | 6 → 3 | R-011 (direct) | All 3 correct (R-012 no longer wrongly flagged GAP) |
| [`pr-8-plan.md`](reports/pr-8-plan.md)  | golf-web-app #8 (N+1)    | 6 → 3 | R-007 (direct) | All 3 correct (R-007 `covered_by` is canonical `"k6 performance gate"`) |
| [`pr-7-plan.md`](reports/pr-7-plan.md)  | golf-web-app #7 (a11y)   | 6 → 2 | R-008 (direct) | All 2 correct |

## Remaining open failure mode

**R-002 over-pull on booking PRs.** Booking-touching PRs still occasionally rank R-002 (concurrent overbooking) at `direct` even when the diff doesn't change concurrency semantics. This is a judgement issue the relevance scale didn't fix — the model genuinely thinks "booking code = R-002 raised". Honest documentation of the limit: the reviewer should sanity-check the top entry on booking-area PRs.

The structural addressable failure modes have been addressed. Further improvement (to R-002 specifically and to ranking quality more broadly) needs *measurement* — a small PR golden set of (diff → expected risks at expected relevance) that we can score the agent against on every change. That is v2 v2.

## v2 v2 — planned

- A small `risk_agent/golden_set.yaml` of historic PRs with expected ranks (id + relevance) and expected `covered_by`. Deterministic scoring like the phase-8 evaluator: set-equality on ranks, exact match on `covered_by`. Treats the agent like any other model under test.
- GitHub Action that posts the plan as a PR comment, gated on a label (`/prioritise`).

## Roadmap (this agent)

- [x] v1: CLI: `--pr` / `--diff` against the parsed register, with structured output
- [x] v1: Evidence captured against four historic SUT PRs
- [x] v2 v1: Deterministic `is_gap` and `covered_by`-enum tightening
- [x] v2 v1: Relevance scale (2/3) self-filtering for lower-rank noise
- [ ] v2 v2: PR golden-set evaluation tier
- [ ] v2 v2: GitHub Action variant
