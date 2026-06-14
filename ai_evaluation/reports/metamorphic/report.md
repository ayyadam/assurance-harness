# Metamorphic evaluation — booking assistant (invariance, v1)

- **Run:** 2026-06-13T23:04:57
- **SUT:** http://localhost:5000 (black-box via `/api/v1/booking-assistant`)
- **Method:** 3 runs/input; modal intent + self-agreement; invariance scored over seeds whose self-agreement ≥ 67%.
- **Seeds:** 10 (10 reliable, 0 unstable-baseline)

## Summary

- **Invariance score: 86%** (51/59 variants kept the seed's intent)
- **Mean seed self-consistency:** 100% (min 100%) — the model's inherent run-to-run stability floor

## Stability by transform

| Transform | Variants stable |
|---|---|
| casing | 85% (17/20) |
| filler | 80% (16/20) |
| synonym | 100% (5/5) |
| typo | 75% (3/4) |
| whitespace | 100% (10/10) |

## Stability by intent dimension

| Dimension | Variants stable |
|---|---|
| dates | 86% (51/59) |
| group_size | 83% (30/36) |
| period | 92% (22/24) |
| players | 67% (8/12) |
| time-window | 100% (12/12) |

## Violations (8)

Each is a meaning-preserving rephrasing that changed the structured intent — a robustness gap.

- **this-saturday-morning** / `casing` (seed self-agreement 100%)
  - seed: `fancy a knock this Saturday morning`
  - variant: `FANCY A KNOCK THIS SATURDAY MORNING`
  - change: group_size: `1` → `4`
- **this-saturday-morning** / `filler` (seed self-agreement 100%)
  - seed: `fancy a knock this Saturday morning`
  - variant: `could you please fancy a knock this Saturday morning`
  - change: group_size: `1` → `2`
- **sunday-fourball** / `casing` (seed self-agreement 100%)
  - seed: `a 4-ball on Sunday`
  - variant: `A 4-BALL ON SUNDAY`
  - change: date: `2026-06-21` → `2026-06-14`
- **threesome-wednesday** / `filler` (seed self-agreement 100%)
  - seed: `a threesome on Wednesday`
  - variant: `a threesome on Wednesday, cheers`
  - change: players: `()` → `('cheers',)`
- **with-dave-sunday** / `casing` (seed self-agreement 100%)
  - seed: `a round with Dave on Sunday`
  - variant: `a round with dave on sunday`
  - change: date: `2026-06-14` → `2026-06-20`
- **with-dave-sunday** / `filler` (seed self-agreement 100%)
  - seed: `a round with Dave on Sunday`
  - variant: `hi, a round with Dave on Sunday`
  - change: date: `2026-06-14` → `2026-06-20`
- **with-dave-sunday** / `filler` (seed self-agreement 100%)
  - seed: `a round with Dave on Sunday`
  - variant: `a round with Dave on Sunday, thanks`
  - change: date: `2026-06-14` → `2026-06-20`
- **with-dave-sunday** / `typo` (seed self-agreement 100%)
  - seed: `a round with Dave on Sunday`
  - variant: `a round wiht Dave on Sunday`
  - change: date: `2026-06-14` → `2026-06-21`

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
