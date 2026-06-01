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

On four diverse PRs across four different test layers, the agent correctly identifies the headline risk at rank #1 every time, with `covered_by` pointing at the layer that already addresses it. That is the part of the plan a reviewer is most likely to act on, and it is reliably right.

One probe the agent suggested on PR #12 that was *not* in the manual exploration: *"setting `not_before` after `not_after` to ensure proper error handling"*. The inverted-window case is now a candidate for a real golden-set entry. The agent surfaced a real coverage idea.

## Known failure modes

These are documented openly because honesty about agent limits is part of the assurance story. Each is observable in the committed evidence:

1. **Lower-ranked entries are noisier than #1.** On every demo PR, ranks #1 (and often #2) are sharp; ranks #4–6 tend to stretch — e.g. PR #7 (a11y) raised R-012 (prompt injection) because the diff touches "user inputs" via CSS/JS. The reviewer should weight the top of the list, not the long tail.
2. **`is_gap` misclassification under low-confidence ranks.** Despite an explicit rule in the system prompt, the agent occasionally marks a *partially-mitigated* risk as a coverage gap (seen on PR #11 for R-012). The structural fix would be to compute `is_gap` deterministically from the parsed status field rather than asking the model — a v2 candidate.
3. **R-002 over-pull on any booking change.** Booking-touching PRs frequently rank R-002 (concurrent overbooking) on the basis that they "change booking logic". Most of the time the diff does not change concurrency semantics. Reviewer should sanity-check before acting.
4. **`covered_by` strings can be malformed.** On PR #8, R-017's `covered_by` was returned as a literal action-version list rather than a layer name. Schema allows any string; tightening this is a v2 candidate.

The pattern is consistent: the agent is reliably useful at the top of its ranking and noisy at the tail. That is exactly the failure mode an advisory tool can tolerate (the reviewer reads top-down and stops where the value ends) but a gate could not.

## v2 candidates

- Compute `is_gap` deterministically from the parsed register `status` field rather than asking the model, so failure mode (2) cannot occur.
- Pin `covered_by` to a closed vocabulary of layer names (an enum, like risk IDs) so failure mode (4) cannot occur.
- Score every risk 0–3 internally, then surface only those ≥2 — addresses failure mode (1).
- GitHub Action that posts the plan as a PR comment, gated on a label (`/prioritise`).
- A small "PR golden set" that records expected #1-ranked risks for each historic PR, scored like the phase-8 deterministic tier. Treats the agent like any other model under test.

## Roadmap (this agent)

- [x] CLI: `--pr` / `--diff` against the parsed register, with structured output
- [x] Evidence captured against four historic SUT PRs
- [ ] Deterministic `is_gap` and `covered_by`-enum tightening (v2)
- [ ] GitHub Action variant (v2)
- [ ] "PR golden set" evaluation tier (phase 12 / "tests of agents")
