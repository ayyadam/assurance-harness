"""CLI for the metamorphic / invariance evaluation of the booking assistant.

Local, on-demand (needs a real Ollama-backed SUT) — like the golden-set eval, it
never runs in hosted CI. Replays a curated set of seed requests AND meaning-
preserving variants of them through the live `/api/v1/booking-assistant`
endpoint, N times each, and asserts the structured intent is invariant.

    uv run python -m ai_evaluation.metamorphic.run            # SUT must be up
    uv run python -m ai_evaluation.metamorphic.run --runs 5

The crux is separating a real robustness finding from LLM noise: each input is
run N times and reduced to its *modal* intent + a *self-agreement* rate. A
variant only counts as a violation when its seed's self-agreement clears a floor
(default 2/3) — otherwise the baseline is too stochastic to judge against, and
the seed is reported as unstable rather than as a finding.

Report (markdown + JSON) lands under ai_evaluation/reports/metamorphic/ as the
committed evidence artifact.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ai_evaluation.evaluator import DEFAULT_BASE_URL, SUTClient, load_cases
from ai_evaluation.metamorphic.relations import (
    IntentKey,
    key_to_fields,
    modal,
    relation_holds,
)
from ai_evaluation.metamorphic.transforms import TRANSFORMS

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "metamorphic"
DEFAULT_RUNS = 3
DEFAULT_RELIABLE_FLOOR = 2 / 3

# Curated seed cases (by golden-set id) spanning every intent dimension.
SEED_IDS = [
    "tomorrow-bare",
    "this-saturday-morning",
    "thursday-afternoon",
    "sunday-fourball",
    "threesome-wednesday",
    "two-of-us-tomorrow",
    "with-dave-sunday",
    "me-dave-sarah-saturday",
    "saturday-from-9am",
    "fourball-saturday-morning-from-9",
]


@dataclass
class VariantResult:
    seed_id: str
    transform: str
    variant_text: str
    variant_modal: IntentKey
    variant_agreement: float
    holds: bool


@dataclass
class SeedResult:
    seed_id: str
    text: str
    categories: list[str]
    seed_modal: IntentKey
    seed_agreement: float
    variants: list[VariantResult] = field(default_factory=list)

    @property
    def reliable(self) -> bool:
        return self.seed_agreement >= DEFAULT_RELIABLE_FLOOR and self.seed_modal is not None


# ── orchestration ────────────────────────────────────────────────────────────


def _run_n(client: SUTClient, text: str, runs: int) -> tuple[IntentKey, float]:
    intents = [client.assist(text)[1] for _ in range(runs)]
    return modal(intents)


def evaluate(client: SUTClient, cases_by_id: dict, runs: int, floor: float) -> list[SeedResult]:
    results: list[SeedResult] = []
    for idx, seed_id in enumerate(SEED_IDS):
        case = cases_by_id[seed_id]
        text = case["input"]
        rng = random.Random(idx)  # deterministic variant generation
        seed_modal, seed_agree = _run_n(client, text, runs)
        sr = SeedResult(seed_id, text, list(case.get("category", [])), seed_modal, seed_agree)

        for tf in TRANSFORMS:
            for variant_text in tf.fn(text, rng):
                v_modal, v_agree = _run_n(client, variant_text, runs)
                holds = relation_holds(seed_modal, v_modal, tf)
                sr.variants.append(VariantResult(seed_id, tf.name, variant_text, v_modal, v_agree, holds))
        results.append(sr)
        print(f"[metamorphic] {seed_id}: self-agreement {seed_agree:.0%}, {len(sr.variants)} variants")
    return results


# ── scoring ──────────────────────────────────────────────────────────────────


def _reliable(results: list[SeedResult]) -> list[SeedResult]:
    return [s for s in results if s.reliable]


def invariance_score(results: list[SeedResult]) -> tuple[int, int]:
    """Held / total variants, over reliable-baseline seeds only."""
    held = total = 0
    for s in _reliable(results):
        for v in s.variants:
            total += 1
            held += v.holds
    return held, total


def by_transform(results: list[SeedResult]) -> dict[str, tuple[int, int]]:
    agg: dict[str, list[int]] = {}
    for s in _reliable(results):
        for v in s.variants:
            a = agg.setdefault(v.transform, [0, 0])
            a[0] += v.holds
            a[1] += 1
    return {k: (v[0], v[1]) for k, v in agg.items()}


def by_category(results: list[SeedResult]) -> dict[str, tuple[int, int]]:
    agg: dict[str, list[int]] = {}
    for s in _reliable(results):
        held = sum(v.holds for v in s.variants)
        total = len(s.variants)
        for cat in s.categories:
            a = agg.setdefault(cat, [0, 0])
            a[0] += held
            a[1] += total
    return {k: (v[0], v[1]) for k, v in agg.items()}


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.0f}%" if d else "—"


# ── reporting ──────────────────────────────────────────────────────────────


def _fields_diff(seed_key: IntentKey, var_key: IntentKey) -> str:
    sf, vf = key_to_fields(seed_key), key_to_fields(var_key)
    if vf is None:
        return "variant produced NO intent (error/empty)"
    if sf is None:
        return "seed produced no intent"
    diffs = [f"{k}: `{sf[k]}` → `{vf[k]}`" for k in sf if sf[k] != vf[k]]
    return "; ".join(diffs) if diffs else "(no field differs)"


def render_markdown(meta: dict, results: list[SeedResult]) -> str:
    held, total = invariance_score(results)
    reliable = _reliable(results)
    unstable = [s for s in results if not s.reliable]
    agrees = [s.seed_agreement for s in results]

    L: list[str] = []
    L.append("# Metamorphic evaluation — booking assistant (invariance, v1)")
    L.append("")
    L.append(f"- **Run:** {meta['run_at']}")
    L.append(f"- **SUT:** {meta['base_url']} (black-box via `/api/v1/booking-assistant`)")
    L.append(
        f"- **Method:** {meta['runs']} runs/input; modal intent + self-agreement; "
        f"invariance scored over seeds whose self-agreement ≥ {meta['floor']:.0%}."
    )
    L.append(f"- **Seeds:** {len(results)} ({len(reliable)} reliable, {len(unstable)} unstable-baseline)")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append(f"- **Invariance score: {_pct(held, total)}** ({held}/{total} variants kept the seed's intent)")
    if agrees:
        L.append(
            f"- **Mean seed self-consistency:** {statistics.fmean(agrees):.0%} "
            f"(min {min(agrees):.0%}) — the model's inherent run-to-run stability floor"
        )
    L.append("")

    L.append("## Stability by transform")
    L.append("")
    L.append("| Transform | Variants stable |")
    L.append("|---|---|")
    for name, (h, t) in sorted(by_transform(results).items()):
        L.append(f"| {name} | {_pct(h, t)} ({h}/{t}) |")
    L.append("")

    L.append("## Stability by intent dimension")
    L.append("")
    L.append("| Dimension | Variants stable |")
    L.append("|---|---|")
    for cat, (h, t) in sorted(by_category(results).items()):
        L.append(f"| {cat} | {_pct(h, t)} ({h}/{t}) |")
    L.append("")

    violations = [(s, v) for s in reliable for v in s.variants if not v.holds]
    L.append(f"## Violations ({len(violations)})")
    L.append("")
    if not violations:
        L.append("_None — every meaning-preserving variant kept the seed's intent (over reliable baselines)._")
    else:
        L.append("Each is a meaning-preserving rephrasing that changed the structured intent — a robustness gap.")
        L.append("")
        for s, v in violations:
            L.append(f"- **{s.seed_id}** / `{v.transform}` (seed self-agreement {s.seed_agreement:.0%})")
            L.append(f"  - seed: `{s.text}`")
            L.append(f"  - variant: `{v.variant_text}`")
            L.append(f"  - change: {_fields_diff(s.seed_modal, v.variant_modal)}")
    L.append("")

    L.append("## Seed self-consistency")
    L.append("")
    L.append("| Seed | Self-agreement | Baseline |")
    L.append("|---|---|---|")
    for s in results:
        flag = "reliable" if s.reliable else "**unstable — excluded from scoring**"
        L.append(f"| {s.seed_id} | {s.seed_agreement:.0%} | {flag} |")
    L.append("")
    return "\n".join(L)


def write_reports(meta: dict, results: list[SeedResult]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / "report.md"
    json_path = REPORTS_DIR / "report.json"
    md_path.write_text(render_markdown(meta, results), encoding="utf-8")
    payload = {"meta": meta, "seeds": [asdict(s) for s in results]}
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Metamorphic invariance eval for the booking assistant.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="runs per input (jitter baseline)")
    parser.add_argument("--reliable-floor", type=float, default=DEFAULT_RELIABLE_FLOOR)
    args = parser.parse_args(argv)

    cases_by_id = {c["id"]: c for c in load_cases()}
    missing = [s for s in SEED_IDS if s not in cases_by_id]
    if missing:
        raise SystemExit(f"seed ids missing from golden set: {missing}")

    client = SUTClient(args.base_url)
    print("[metamorphic] warming up the model ...")
    client.assist("tomorrow morning")  # warm the model so the first timed call isn't cold

    results = evaluate(client, cases_by_id, args.runs, args.reliable_floor)
    meta = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "runs": args.runs,
        "floor": args.reliable_floor,
        "seeds": len(SEED_IDS),
    }
    md_path, json_path = write_reports(meta, results)
    held, total = invariance_score(results)
    print(f"[metamorphic] invariance score {_pct(held, total)} ({held}/{total})")
    print(f"[metamorphic] wrote {md_path}")
    print(f"[metamorphic] wrote {json_path}")


if __name__ == "__main__":
    main()
