# Exploratory testing agent

LLM-driven exploratory probing that complements the deterministic spine
(contract / functional / a11y / perf / data quality) with **adversarial
creativity** the rule-based layers don't have. Two surfaces:

- **API** (`explore_agent.run`, phase 12 v1 v1) — drives from the live
  OpenAPI spec, asks the LLM to propose payload variants per endpoint, then
  classifies each response.
- **UI** (`explore_agent.ui_run`, phase 12 v1 v3 — adaptive) — drives
  Playwright through predefined tours, asks the LLM to decide one action at a
  time from the *current* page state (an adaptive policy, not an upfront plan),
  then judges each step.

Both surfaces share the same shape: **LLM proposes, deterministic harness
executes, LLM judges**, with a closed-enum finding category that bounds the
output. Both are **local-only**, advisory, never a CI gate.

## API surface — `explore_agent.run`

1. Fetch the live OpenAPI spec from the SUT (`/api/v1/openapi.json`).
2. For each endpoint, ask the LLM for three request variants:
   - **happy** — minimal valid body
   - **edge** — boundary values (empty strings, missing optionals, oversize
     legal strings, date boundaries, unicode quirks)
   - **abusive** — injection-style strings, oversize payloads, wrong types,
     prompt-injection probes on AI-backed endpoints
3. Authenticate as a seeded member, send each probe, capture response.
4. Ask the LLM to classify each response:
   - `expected` / `unexpected_5xx` / `schema_drift` / `business_rule_concern`
5. Render to `explore_agent/reports/report.md` and `report.json`.

### API quick start

The SUT must be running locally:

```bash
# from golf-web-app/
docker compose up -d
docker compose exec web python seed.py
```

Then:

```bash
# default model (qwen2.5:32b-instruct-q4_K_M) on local Ollama
uv run python -m explore_agent.run

# alternative model
uv run python -m explore_agent.run --model qwen3:8b-fp16

# deterministic-only — no LLM payloads, no LLM judgement
uv run python -m explore_agent.run --no-llm
```

## UI surface — `explore_agent.ui_run`

The UI agent is an adaptive **policy**, not a fixed plan: it decides one action
at a time from the page it can currently see, so it cannot reference a selector
on a page it has not yet perceived (which is exactly what the earlier plan-based
version did — see [Known limitations](#known-limitations-v1-v3)).

1. For each predefined tour (see [`tours.py`](tours.py)):
   - If the tour requires auth, the executor logs in via the UI form first.
   - Navigate to the tour's starting URL.
   - **Loop** (`ui_probe.run_tour`), up to the tour's step budget:
     - **Perceive** — snapshot the current page (URL, title, interactive
       elements actually present).
     - **Decide** — ask the LLM for the single next action, given the current
       page + the history so far. It chooses `navigate` / `click` / `fill` /
       `wait` / `observe`, or `finish` (goal reached, or stuck — with a reason).
     - **Act** — drive Playwright through that one action, capturing URL, page
       title, JS console errors, network 5xx, and a screenshot. Then re-perceive
       and decide again.
   - **Judge**: ask the LLM to classify each step's outcome:
     - `expected` / `unexpected_5xx` / `js_error` / `dead_end` /
       `business_rule_concern`
2. Render to `explore_agent/reports/ui/report.md` + `report.json` +
   per-step screenshots under `explore_agent/reports/ui/screenshots/`.

### UI quick start

Same SUT prereqs. Then:

```bash
# all tours, headless
uv run python -m explore_agent.ui_run

# single tour
uv run python -m explore_agent.ui_run --tour booking-assistant

# see the browser
uv run python -m explore_agent.ui_run --headed
```

The first run downloads Chromium if not already cached:

```bash
uv run playwright install chromium
```

## Closed-enum categories — what they mean

| Category | API | UI | Meaning |
|---|---|---|---|
| `expected` | ✓ | ✓ | Behaviour matches the documented intent. A 4xx rejecting an abusive payload that the schema clearly disallows is **expected**, not a finding. |
| `unexpected_5xx` | ✓ | ✓ | A 5xx surfaced. Even abusive input should be rejected with a 4xx. |
| `schema_drift` | ✓ | — | Response body diverges from the documented schema (API only). |
| `js_error` | — | ✓ | Console / page error captured during the step (UI only). |
| `dead_end` | — | ✓ | The step's intended action did not execute (selector not found, exception raised) and the tour cannot progress. |
| `business_rule_concern` | ✓ | ✓ | Response/state is technically valid but the outcome is suspect — accepts a past-date booking, exposes sensitive data, leaks internals via error messages. |

Findings are **advisory leads to investigate**, not defect tickets.

## Known limitations (v1 v3)

These are limits of LLM-jittered exploration. They show up cleanly in the
report rather than as silent skips — that visibility is part of the value.

- **API surface — judge mislabels some 2xx/4xx as `unexpected_5xx`.** The
  LLM uses the category as "this response surprised me" even when the
  status code is in the 200s/400s. Filter on `status >= 500` in the report
  if you want strict 5xx only.
- **API surface — no temporal context.** The agent doesn't know today's
  date and will sometimes flag "future dates" that are actually today.
- **UI surface — perception covers interactive controls, not result content.**
  The page snapshot lists `a` / `button` / `input` / `textarea` / `select`
  only. When a tour's *success* shows up as non-interactive content — e.g. the
  booking assistant renders its suggested slots as `<div onclick=…>` cards, not
  buttons — the agent cannot perceive that the result arrived, so it cannot
  confidently `finish` and instead exhausts its step budget `observe`-ing. This
  is the successor to the now-fixed plan-once hallucination: v1 v3 replaced the
  upfront plan with a policy (see F-026), which made inventing selectors for
  unseen pages structurally impossible, and in doing so surfaced this perception
  gap cleanly. Tracked as **F-028** (widen perception to `[onclick]` / `[role]`
  / `[tabindex]`, with a check that scope limits like "do not confirm" still hold).
- **UI surface — judge can mistake intermediate fills for divergence.** A
  `fill #password` step that leaves you on the same `/auth/login` page is the
  *correct* intermediate state, but the judge can read "still on login page" as
  a goal-divergence and tag it `dead_end` even though the step succeeded and the
  tour goes on to finish. Read per-step judgement with the tour goal in mind.
  Tracked as **F-027** (anchor `dead_end` on the executor's `succeeded` signal
  rather than on an inferred URL change).

## Eval surface — `explore_agent.eval`

Golden-set evaluation tier (v2 v1) mirroring [`risk_agent.eval`](../risk_agent/eval.py)
and [`triage_agent.eval`](../triage_agent/eval.py). Reads the cached
API-surface report and scores each (endpoint, variant) probe's category
against the expected category in [`golden_set.yaml`](golden_set.yaml).
Deterministic — no LLM in the scoring path.

### Eval quick start

```bash
# score the cached report
uv run python -m explore_agent.eval

# re-run the API agent first, then score
uv run python -m explore_agent.eval --refresh
```

### What this eval measures

With no defects in the seeded surface, every golden-set case's expected
category is `expected`. The eval quantifies one specific failure mode:
**how often the agent over-flags benign responses** (the documented v1 v1
limitation). Future judge-prompt tightening, prompt-engineering tweaks,
or a different judge model can all be scored against this baseline.

Current baseline (post-7-day reseed):

| Metric | Value |
|---|---|
| Cases | 18 |
| Overall accuracy | **0.500** (9/18) |
| Over-flagged as `business_rule_concern` | 7 |
| Over-flagged as `unexpected_5xx` | 2 |

If a real defect surfaces later, the affected case is updated to a
non-`expected` category and the same scorer also measures whether the
agent **catches real defects** — without changes to the eval code.

## Scope (v1)

- **API**: every v1 endpoint probed with three payload variants,
  authenticated as the seeded `john.smith` account.
- **UI**: three predefined tours (public pages, member login + dashboard,
  booking-assistant interaction).
- **Eval**: 18 (endpoint, variant) cases scored deterministically against
  the cached API report.

## Roadmap and deferred work

This README intentionally does not maintain its own backlog — the single
source of truth is the **Phase 12 sub-roadmap** in
[`docs/test-strategy.md` §12](../docs/test-strategy.md#phase-12-sub-roadmap).
That section tracks the delivered sub-versions plus the deferred items beyond
(free-form exploration, state-mutating tours, cross-tour memory, and the two
items the v1 v3 adaptive rewrite surfaced — judge-signal sharpening (F-027) and
wider perception (F-028)). Read there for what's next and why.
