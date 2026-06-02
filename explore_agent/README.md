# Exploratory testing agent — API-level (phase 12 v1 v1)

An LLM-driven exploratory agent that probes the live SUT API for issues a
scripted test wouldn't find. It complements the deterministic spine
(contract/perf/a11y/data-quality/functional) by exercising the same
endpoints with **adversarial creativity** the rule-based layers don't have.

## What it does

1. Fetch the live OpenAPI spec from the SUT (`/api/v1/openapi.json`).
2. For each endpoint, ask a local LLM to propose three request payload
   variants:
   - **happy** — minimal valid body
   - **edge** — boundary values (empty strings, missing optionals, oversize
     legal strings, date boundaries, unicode quirks)
   - **abusive** — injection-style strings, oversize payloads, wrong types,
     prompt-injection probes on AI-backed endpoints
3. Authenticate as a seeded member, send each probe, capture response.
4. Ask the LLM to classify each response into one of four categories:
   - `expected`
   - `unexpected_5xx`
   - `schema_drift`
   - `business_rule_concern`
5. Render a markdown + JSON report, ranking findings by category and
   severity.

## Why local-only

Same cadence as [`risk_agent`](../risk_agent/) and
[`triage_agent`](../triage_agent/): the agentic layer is advisory and
LLM-jittered, so it is run *locally before pushing* rather than gating CI.
The deterministic layers gate; the agents inform.

## Quick start

The SUT must be running locally (see [`golf-web-app/README.md`](../../golf-web-app/README.md)):

```bash
# from golf-web-app/
docker compose up -d
docker compose exec web python seed.py
```

Then from `testing-system/`:

```bash
# default model (qwen2.5:32b-instruct-q4_K_M) on local Ollama
uv run python -m explore_agent.run

# alternative model
uv run python -m explore_agent.run --model qwen3:8b-fp16

# deterministic-only — no LLM payloads, no LLM judgement
uv run python -m explore_agent.run --no-llm
```

Reports land under `explore_agent/reports/` (committed as evidence
artefacts, alongside the other agent outputs).

## Scope and out-of-scope (v1 v1)

In scope:
- API-level probing of every endpoint in the v1 spec
- Authenticated probes via the seeded `john.smith` account
- LLM-driven payload generation + response classification
- Per-endpoint path-param resolution via a small seed-context lookup

Deferred:
- **v1 v2** — UI-level exploration (Playwright-driven, LLM picks pages
  and inputs)
- **v2 v1** — golden-set eval for the explore agent itself, mirroring
  the eval tiers built for [`risk_agent`](../risk_agent/eval.py) and
  [`triage_agent`](../triage_agent/eval.py)
- **v2 v2** — adversarial regression tests on the existing agents
  (jitter / robustness)
- Auth-bypass probing (sending requests without credentials, with wrong
  credentials, with another member's token) — would belong in a dedicated
  security-focused pass

## Categories — what they mean

| Category | Meaning |
|---|---|
| `expected` | Status + body match documented behaviour. A 4xx rejecting an abusive payload that the schema clearly disallows is **expected**, not a finding. |
| `unexpected_5xx` | Server returned 5xx. Even abusive input should be rejected with a 4xx, not crash. |
| `schema_drift` | Response shape diverges from the documented schema for that status — undocumented fields, missing required fields, wrong types, undocumented status codes. |
| `business_rule_concern` | Response is technically valid per the schema but the outcome is suspect — accepts a past-date booking, returns sensitive data, leaks internals via an error message, etc. |

The judgement is advisory. Treat findings as **leads to investigate**,
not defect tickets.
