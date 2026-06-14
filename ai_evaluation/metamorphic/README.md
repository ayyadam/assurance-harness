# Metamorphic / invariance evaluation

The second evaluation method over the booking assistant (see the [parent README](../README.md)). Where the golden set asks *"is the intent correct for these exact phrasings?"*, this asks *"is the intent **stable** across meaning-preserving rephrasings?"* — the robustness a fixed golden set cannot express, and the real-world failure mode of an LLM feature (users type typos, abbreviations, filler, reordered clauses — not your canonical phrasings).

## The idea

Metamorphic testing sidesteps the LLM "oracle problem" (you can't enumerate the exact correct output for free text) by asserting **relations between the outputs of related inputs** instead of exact outputs:

- **v1 — invariance:** transform a seed request in a way that *shouldn't* change its meaning → the structured `BookingIntent` must be **unchanged**.
- **v2 — directional** (next): transform it in a way that *should* change one field predictably (e.g. `4-ball → 2-ball`) → that field changes, everything else stays put. The framework in [`relations.py`](relations.py) (`expected_variant_key`) is built for this.

## Transforms ([`transforms.py`](transforms.py))

Each turns a seed into meaning-preserving variants. The honest hard part is keeping them *genuinely* equivalent — a sloppy "synonym" that drifts meaning manufactures a false violation — so:

| Transform | Example | Why it's safe |
|---|---|---|
| `casing` | `Book a 4-BALL saturday` | the parser lower-cases internally |
| `whitespace` | doubled spaces / trailing | cosmetic only |
| `filler` | `could you please book…`, `…, thanks` | adds no booking information |
| `typo` | one transposed char on a **non-semantic** word | never touches weekdays/numbers/periods/times/names |
| `synonym` | `4-ball → foursome`, `knock → round` | a **curated golf-domain map**, not a generic thesaurus |

## The crux — telling a finding from LLM noise

The model is nondeterministic, so "different intent for a rephrase" could just be sampling jitter. The method separates the two:

1. Run every input **N times** (default 3) → reduce to its **modal intent** (most frequent) + a **self-agreement** rate (how consistent the model is on *that* input).
2. A variant is a **violation** only when it diverges from its seed's modal intent **and** the seed's self-agreement clears a floor (default **2/3**). Below the floor the baseline is too stochastic to judge against, so the seed is reported as **unstable — excluded from scoring**, not as a finding.

This is the same jitter discipline the agent regression tests use (measure N before concluding).

## Output ([`reports/metamorphic/`](../reports/metamorphic/))

`report.md` + `report.json`:
- **Invariance score** (variants that kept the seed's intent, over reliable baselines).
- **Stability by transform** — *which* perturbation the model is most fragile to (the actionable axis).
- **Stability by intent dimension** (date / period / group_size / players / time-window).
- **Violations** — each fragile rephrasing with the seed→variant field diff.
- **Seed self-consistency** — per-seed agreement, flagging unstable baselines.

## Running

Local, on-demand — needs a real Ollama-backed SUT (the SUT's provider defaults to a deterministic stub, so point it at a model first; the harness standard is `qwen2.5:32b-instruct-q4_K_M`). Never runs in hosted CI.

```bash
# SUT must be up and pointed at an LLM provider (not the stub).
uv run python -m ai_evaluation.metamorphic.run            # N=3
uv run python -m ai_evaluation.metamorphic.run --runs 5   # tighter statistics
```

The transforms + intent machinery are covered by fast, gated unit tests ([`tests/test_metamorphic_transforms.py`](../../tests/test_metamorphic_transforms.py)) that run in the standard pytest gate (no SUT/LLM) — they assert the transforms are meaning-preserving *by construction*.

## Honest limitations

- **You define the equivalence classes.** Casing is unambiguous; some synonyms are judgement calls — hence the deliberately conservative, curated map.
- **Tests the LLM intent extraction only** — the deterministic spine around it (validation, slot-finding) is covered by ordinary unit tests. That's by design: metamorphic targets the one nondeterministic component, which is the SUT's stated safety boundary.
- **Specific to the SUT having an AI feature** — the *technique* transfers to any LLM feature; this *suite* is bound to the booking assistant.
