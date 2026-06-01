# AI evaluation report — booking assistant

- **Run:** 2026-05-29T21:56:18  (today = 2026-05-29)
- **SUT:** http://localhost:5000 (black-box via `/api/v1/booking-assistant`)
- **Golden set:** 31 cases
- **Grading:** deterministic field scoring; safety cases graded on no-5xx + in-schema + clamped. Latency is warm (model pre-loaded before timing).

## Summary

| Model | Field accuracy | Cases fully correct | Safety | Latency p50 / mean / max (s) |
|---|---|---|---|---|
| `qwen3:8b-fp16` | 80% (129/162) | 7/27 | 4/4 | 1.2 / 1.2 / 1.5 |
| `qwen2.5:14b-instruct-q8_0` | 92% (149/162) | 15/27 | 4/4 | 2.1 / 2.1 / 2.5 |
| `qwen3.6:27b-q4_K_M` | 97% (157/162) | 22/27 | 4/4 | 2.5 / 2.6 / 3.0 |
| `qwen2.5:32b-instruct-q4_K_M` | 95% (154/162) | 20/27 | 4/4 | 2.6 / 2.6 / 3.0 |
| `qwen3.6-40k-think:latest` | 96% (156/162) | 21/27 | 4/4 | 2.4 / 2.5 / 2.8 |

## Field accuracy by category

| Category | `qwen3:8b-fp16` | `qwen2.5:14b-instruct-q8_0` | `qwen3.6:27b-q4_K_M` | `qwen2.5:32b-instruct-q4_K_M` | `qwen3.6-40k-think:latest` |
|---|---|---|---|---|---|
| dates | 80% | 92% | 97% | 95% | 96% |
| group_size | 83% | 95% | 100% | 98% | 100% |
| period | 80% | 95% | 100% | 100% | 100% |
| players | 83% | 93% | 100% | 97% | 100% |
| time-window | 67% | 88% | 90% | 88% | 90% |

## Failures

### `qwen3:8b-fp16` — 20 failing case(s)
- **this-morning** — date: got `2026-05-30` want `2026-05-29`
- **this-saturday-morning** — date: got `2026-06-06` want `2026-05-30`; group_size: got `2` want `1`
- **next-tuesday-bare** — date: got `2026-06-08` want `2026-06-09`
- **in-three-days** — date: got `2026-06-03` want `2026-06-01`
- **thursday-afternoon** — date: got `2026-06-03` want `2026-06-04`
- **sunday-fourball** — date: got `2026-06-07` want `2026-05-31`
- **this-afternoon** — date: got `2026-06-05` want `2026-05-29`
- **tomorrow-evening** — date: got `2026-06-03` want `2026-05-30`; period: got `any` want `afternoon`
- **just-me-saturday** — date: got `2026-06-06` want `2026-05-30`; period: got `morning` want `any`
- **me-and-three-mates** — period: got `morning` want `any`; players: got `['three mates']` want `[]`
- **with-dave-sunday** — date: got `2026-06-07` want `2026-05-31`
- **me-dave-sarah-saturday** — date: got `2026-06-06` want `2026-05-30`
- **saturday-from-9am** — date: got `2026-06-06` want `2026-05-30`; period: got `morning` want `any`
- **tomorrow-before-noon** — date: got `2026-06-02` want `2026-05-30`; period: got `morning` want `any`
- **monday-between-10-12** — date: got `2026-06-07` want `2026-06-01`; period: got `afternoon` want `any`
- **sunday-after-2pm** — date: got `2026-06-07` want `2026-05-31`; period: got `afternoon` want `any`; not_before: got `None` want `14:00:00`; not_after: got `14:00:00` want `None`
- **saturday-at-10am** — date: got `2026-06-06` want `2026-05-30`; period: got `morning` want `any`
- **tomorrow-no-later-than-11** — date: got `2026-06-02` want `2026-05-30`
- **two-tomorrow-afternoon-before-3** — date: got `2026-06-02` want `2026-05-30`; not_before: got `15:00:00` want `None`; not_after: got `None` want `15:00:00`
- **me-dave-tuesday-anytime** — date: got `2026-06-08` want `2026-06-02`

### `qwen2.5:14b-instruct-q8_0` — 12 failing case(s)
- **this-morning** — date: got `2026-05-30` want `2026-05-29`
- **next-tuesday-bare** — date: got `2026-06-03` want `2026-06-09`
- **thursday-afternoon** — date: got `2026-05-29` want `2026-06-04`
- **this-afternoon** — date: got `2026-05-30` want `2026-05-29`
- **threesome-wednesday** — date: got `2026-06-01` want `2026-06-03`
- **me-and-three-mates** — players: got `['three mates']` want `[]`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — date: got `2026-05-31` want `2026-06-01`; period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`
- **me-dave-tuesday-anytime** — date: got `2026-06-03` want `2026-06-02`

### `qwen3.6:27b-q4_K_M` — 5 failing case(s)
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`

### `qwen2.5:32b-instruct-q4_K_M` — 7 failing case(s)
- **next-tuesday-bare** — date: got `2026-06-02` want `2026-06-09`
- **me-and-three-mates** — players: got `['mates']` want `[]`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — period: got `morning` want `any`; group_size: got `4` want `1`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`

### `qwen3.6-40k-think:latest` — 6 failing case(s)
- **next-tuesday-bare** — date: got `2026-06-02` want `2026-06-09`
- **saturday-from-9am** — period: got `morning` want `any`
- **tomorrow-before-noon** — period: got `morning` want `any`
- **monday-between-10-12** — period: got `morning` want `any`
- **sunday-after-2pm** — period: got `afternoon` want `any`
- **saturday-at-10am** — period: got `morning` want `any`
