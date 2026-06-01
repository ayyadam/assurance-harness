# AI evaluation report — booking assistant

- **Run:** 2026-06-01T13:19:20  (today = 2026-06-01)
- **SUT:** http://localhost:5000 (black-box via `/api/v1/booking-assistant`)
- **Golden set:** 40 cases
- **Grading:** deterministic field scoring; safety cases graded on no-5xx + in-schema + clamped. Latency is warm (model pre-loaded before timing).

## Summary

| Model | Field accuracy | Cases fully correct | Safety | Latency p50 / mean / max (s) |
|---|---|---|---|---|
| `qwen3:8b-fp16` | 86% (140/162) | 12/27 | 7/7 | 1.2 / 1.2 / 1.5 |
| `qwen2.5:14b-instruct-q8_0` | 93% (150/162) | 17/27 | 7/7 | 2.0 / 2.1 / 2.4 |
| `qwen3.6:27b-q4_K_M` | 96% (155/162) | 21/27 | 7/7 | 2.5 / 2.6 / 2.9 |
| `qwen2.5:32b-instruct-q4_K_M` | 94% (152/162) | 19/27 | 7/7 | 2.6 / 2.6 / 3.0 |
| `qwen3.6-40k-think:latest` | 96% (155/162) | 20/27 | 7/7 | 2.4 / 2.5 / 2.8 |

## Judge summary

_LLM-judge: `qwen2.5:32b-instruct-q4_K_M`. Holistic = 0-10 reasonableness across every captured case. Fuzzy = pass-rate on cases where deterministic field equality is too strict (graded against a per-case rubric)._

| Model | Holistic mean (0-10) | Fuzzy passed |
|---|---|---|
| `qwen3:8b-fp16` | 6.3 | 5/6 |
| `qwen2.5:14b-instruct-q8_0` | 6.8 | 5/6 |
| `qwen3.6:27b-q4_K_M` | 6.7 | 4/6 |
| `qwen2.5:32b-instruct-q4_K_M` | 7.0 | 5/6 |
| `qwen3.6-40k-think:latest` | 6.6 | 5/6 |

## Field accuracy by category

| Category | `qwen3:8b-fp16` | `qwen2.5:14b-instruct-q8_0` | `qwen3.6:27b-q4_K_M` | `qwen2.5:32b-instruct-q4_K_M` | `qwen3.6-40k-think:latest` |
|---|---|---|---|---|---|
| dates | 86% | 93% | 96% | 94% | 96% |
| group_size | 88% | 92% | 98% | 95% | 97% |
| period | 90% | 97% | 100% | 98% | 98% |
| players | 90% | 90% | 97% | 93% | 97% |
| time-window | 75% | 85% | 88% | 88% | 88% |

## Failures

### `qwen3:8b-fp16` — 16 failing case(s)
- **this-saturday-morning** — group_size: got `2` want `1`
- **next-tuesday-bare** — date: got `2026-06-08` want `2026-06-09`
- **in-three-days** — date: got `2026-06-05` want `2026-06-04`
- **this-afternoon** — date: got `2026-06-05` want `2026-06-01`
- **tomorrow-evening** — period: got `any` want `afternoon`
- **just-me-saturday** — period: got `morning` want `any`
- **threesome-wednesday** — date: got `2026-06-10` want `2026-06-03`
- **me-and-three-mates** — date: got `2026-06-06` want `2026-06-13`; period: got `morning` want `any`; players: got `['three mates']` want `[]`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — date: got `2026-06-08` want `2026-06-01`; period: got `afternoon` want `any`
- **sunday-after-2pm** — date: got `2026-06-06` want `2026-06-07`; period: got `afternoon` want `any`; not_before: got `None` want `14:00:00`; not_after: got `14:00:00` want `None`
- **saturday-at-10am** — period: got `morning` want `any`
- **fourball-saturday-morning-from-9** — date: got `2026-06-06` want `2026-06-13`
- **two-tomorrow-afternoon-before-3** — not_before: got `15:00:00` want `None`; not_after: got `None` want `15:00:00`
- **around-lunchtime** (fuzzy) — judge: The assistant's interpretation does not satisfy the rubric because it lacks appropriate `not_before` and `not_after` constraints. Although the date is correctly set to tomorrow and the period is reasonable as 'afternoon', the absence of time bounds makes the constraint too loose.

### `qwen2.5:14b-instruct-q8_0` — 11 failing case(s)
- **this-afternoon** — date: got `2026-06-05` want `2026-06-01`
- **threesome-wednesday** — date: got `2026-06-08` want `2026-06-03`
- **me-and-three-mates** — date: got `2026-06-10` want `2026-06-13`; players: got `['three mates']` want `[]`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — date: got `2026-06-02` want `2026-06-01`; period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`
- **fourball-saturday-morning-from-9** — date: got `2026-06-10` want `2026-06-13`
- **me-dave-tuesday-anytime** — date: got `2026-06-03` want `2026-06-02`
- **around-lunchtime** (fuzzy) — judge: The assistant's interpretation does not satisfy the rubric because it lacks appropriate `not_before` and `not_after` constraints. Although the date is correctly set to tomorrow and the period is reasonable as 'afternoon', the absence of time bounds makes the constraint too loose.

### `qwen3.6:27b-q4_K_M` — 8 failing case(s)
- **me-and-three-mates** — date: got `2026-06-06` want `2026-06-13`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — date: got `2026-06-08` want `2026-06-01`; period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`
- **around-lunchtime** (fuzzy) — judge: The assistant's interpretation does not satisfy the rubric because it lacks appropriate `not_before` and `not_after` constraints. Although the date is correctly set to tomorrow and the period is reasonable as 'afternoon', the absence of time bounds makes the constraint too loose.
- **weekend-with-mates** (fuzzy) — judge: The assistant's interpretation does not satisfy the rubric because the group_size is 1 instead of between 2 and 4. Additionally, the date should be either Saturday or Sunday of the upcoming weekend, but '2026-06-06' may not necessarily fall on a weekend.

### `qwen2.5:32b-instruct-q4_K_M` — 9 failing case(s)
- **thursday-afternoon** — date: got `2026-06-05` want `2026-06-04`
- **threesome-wednesday** — date: got `2026-06-08` want `2026-06-03`
- **me-and-three-mates** — date: got `2026-06-06` want `2026-06-13`; players: got `['mates']` want `[]`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — date: got `2026-06-08` want `2026-06-01`; period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`
- **around-lunchtime** (fuzzy) — judge: The assistant's interpretation does not satisfy the rubric because it lacks appropriate `not_before` and `not_after` constraints. Although the date is correctly set to tomorrow and the period is reasonable as 'afternoon', the absence of time bounds makes the constraint too loose.

### `qwen3.6-40k-think:latest` — 8 failing case(s)
- **me-and-three-mates** — date: got `2026-06-06` want `2026-06-13`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`
- **fourball-saturday-morning-from-9** — date: got `2026-06-06` want `2026-06-13`
- **around-lunchtime** (fuzzy) — judge: The assistant's interpretation does not satisfy the rubric because it lacks appropriate `not_before` and `not_after` constraints. Although the date is correctly set to tomorrow and the period is reasonable as 'afternoon', the absence of time bounds makes the constraint too loose.
