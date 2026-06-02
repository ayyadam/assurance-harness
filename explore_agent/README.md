# Exploratory testing agent

LLM-driven exploratory probing that complements the deterministic spine
(contract / functional / a11y / perf / data quality) with **adversarial
creativity** the rule-based layers don't have. Two surfaces:

- **API** (`explore_agent.run`, phase 12 v1 v1) — drives from the live
  OpenAPI spec, asks the LLM to propose payload variants per endpoint, then
  classifies each response.
- **UI** (`explore_agent.ui_run`, phase 12 v1 v2) — drives Playwright
  through predefined tours, asks the LLM to plan each tour from the starting
  page state, then judges each step.

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

1. For each predefined tour (see [`tours.py`](tours.py)):
   - If the tour requires auth, the executor logs in via the UI form first.
   - Navigate to the tour's starting URL.
   - **Plan**: ask the LLM for a step plan (≤ tour budget), given the
     starting page state (URL, title, interactive elements visible).
   - **Execute**: drive Playwright through each step (navigate / click /
     fill / wait / observe), capturing per-step:
     - URL, page title, JS console errors, network 5xx, screenshot
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

## Known limitations (v1 v2)

These are limits of LLM-jittered exploration. They show up cleanly in the
report rather than as silent skips — that visibility is part of the value.

- **API surface — judge mislabels some 2xx/4xx as `unexpected_5xx`.** The
  LLM uses the category as "this response surprised me" even when the
  status code is in the 200s/400s. Filter on `status >= 500` in the report
  if you want strict 5xx only.
- **API surface — no temporal context.** The agent doesn't know today's
  date and will sometimes flag "future dates" that are actually today.
- **UI surface — plan-once-from-starting-page.** The planner sees the
  starting page's interactive elements only. When planning further into the
  app (e.g. clicking a link, then expecting selectors on the next page) it
  invents plausible-but-non-existent selectors. These surface as `dead_end`
  steps with the invented selector visible — easy for a reviewer to spot
  and adjust their mental model.
- **UI surface — judge can mistake intermediate fills for divergence.** A
  `fill #password` step that leaves you on the same `/auth/login` page is
  the *correct* intermediate state, but the judge can read "still on
  login page" as a goal-divergence and tag it `dead_end`. Read per-step
  judgement with the tour goal in mind.

## Scope and out-of-scope

In scope (v1):
- API: every v1 endpoint, three payload variants each, authenticated as
  the seeded `john.smith` account.
- UI: three predefined tours (public pages, member login + dashboard,
  booking assistant interaction).

Deferred (v2 candidates):
- **v2 v1** — golden-set eval for the explore agent itself, mirroring the
  eval tiers built for [`risk_agent`](../risk_agent/eval.py) and
  [`triage_agent`](../triage_agent/eval.py).
- **v2 v2** — adversarial / robustness regression tests on the existing
  `risk_agent` and `triage_agent` (LLM run N times, check invariants hold).
- Free-form UI exploration (LLM picks the goal).
- Re-planning mid-tour (so the plan can adapt as new pages reveal new
  selectors).
- Auth-bypass probing (no-cred / wrong-cred / other-user-cred probes on
  the API surface).
