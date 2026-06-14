# Metamorphic evaluation — booking assistant (invariance + directional)

- **Run:** 2026-06-14T08:39:03
- **SUT:** http://localhost:5000 (black-box via `/api/v1/booking-assistant`)
- **Method:** 3 runs/input; modal intent + self-agreement; invariance scored over seeds whose self-agreement ≥ 67%.
- **Seeds:** 10 (10 reliable, 0 unstable-baseline)

## Summary

- **Invariance score: 92%** (54/59 variants kept the seed's intent)
- **Directional score: 100%** (9/9 variants changed exactly the intended field and nothing else)
- **Mean seed self-consistency:** 100% (min 100%) — the model's inherent run-to-run stability floor

## Stability by transform

| Transform | Variants stable |
|---|---|
| casing | 90% (18/20) |
| filler | 95% (19/20) |
| synonym | 80% (4/5) |
| typo | 75% (3/4) |
| whitespace | 100% (10/10) |

## Stability by intent dimension

| Dimension | Variants stable |
|---|---|
| dates | 92% (54/59) |
| group_size | 89% (32/36) |
| period | 88% (21/24) |
| players | 100% (12/12) |
| time-window | 83% (10/12) |

## Violations (5)

Each is a meaning-preserving rephrasing that changed the structured intent — a robustness gap.

- **this-saturday-morning** / `casing` (seed self-agreement 100%)
  - seed: `fancy a knock this Saturday morning`
  - variant: `FANCY A KNOCK THIS SATURDAY MORNING`
  - change: group_size: `1` → `4`
- **threesome-wednesday** / `filler` (seed self-agreement 100%)
  - seed: `a threesome on Wednesday`
  - variant: `a threesome on Wednesday, cheers`
  - change: date: `2026-06-17` → `2026-06-18`; players: `()` → `('cheers',)`
- **threesome-wednesday** / `synonym` (seed self-agreement 100%)
  - seed: `a threesome on Wednesday`
  - variant: `a 3-ball on Wednesday`
  - change: date: `2026-06-17` → `2026-06-18`
- **fourball-saturday-morning-from-9** / `casing` (seed self-agreement 100%)
  - seed: `a 4-ball next Saturday morning from 9am`
  - variant: `A 4-BALL NEXT SATURDAY MORNING FROM 9AM`
  - change: date: `2026-06-20` → `2026-06-27`
- **fourball-saturday-morning-from-9** / `typo` (seed self-agreement 100%)
  - seed: `a 4-ball next Saturday morning from 9am`
  - variant: `a 4-ball netx Saturday morning from 9am`
  - change: date: `2026-06-20` → `2026-06-27`

## Directional relations (v2)

Meaning-*changing* rephrasings: exactly one field should change predictably, the rest unchanged.

| Relation | Correct |
|---|---|
| group:4-ball→threesome | 100% (2/2) |
| group:threesome→foursome | 100% (1/1) |
| period→afternoon | 100% (3/3) |
| period→morning | 100% (1/1) |
| time:9am→11am | 100% (2/2) |

### Directional violations (0)

_None — every directional rephrasing produced exactly the expected change._

## Seed self-consistency

| Seed | Self-agreement | Baseline |
|---|---|---|
| tomorrow-bare | 100% | reliable |
| this-saturday-morning | 100% | reliable |
| thursday-afternoon | 100% | reliable |
| sunday-fourball | 100% | reliable |
| threesome-wednesday | 100% | reliable |
| two-of-us-tomorrow | 100% | reliable |
| with-dave-sunday | 100% | reliable |
| me-dave-sarah-saturday | 100% | reliable |
| saturday-from-9am | 100% | reliable |
| fourball-saturday-morning-from-9 | 100% | reliable |
