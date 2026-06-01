"""Risk-prioritisation agent — golden-set evaluation tier (v2 v2).

Treats the agent like any other model under test. The golden set
(``golden_set.yaml``) records, per historic PR, the register risks a reviewer
would call relevant at the relevance they warrant. The evaluator compares the
agent's actual output (read from ``reports/pr-N-plan.json``) against the
expected set and reports precision / recall / F1, plus relevance accuracy on
the true positives.

This is deterministic — no LLM in the scoring path. The agent's raw output is
the cached JSON report, which can be refreshed with ``--refresh`` (re-runs the
agent against the live PR diffs before scoring). Score-only re-runs after a
golden-set edit are free.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from risk_agent.agent import DEFAULT_MODEL, prioritise
from risk_agent.diff import fetch_pr
from risk_agent.register import parse_register

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.yaml"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


@dataclass
class CaseScore:
    case_id: str
    pr: int
    title: str
    expected: dict[str, int]  # {risk_id: relevance}
    actual: dict[str, int]  # {risk_id: relevance}
    true_positives: set[str]
    false_positives: set[str]
    false_negatives: set[str]
    relevance_correct: int  # count of TPs with matching relevance

    @property
    def precision(self) -> float:
        denom = len(self.true_positives) + len(self.false_positives)
        return len(self.true_positives) / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = len(self.true_positives) + len(self.false_negatives)
        return len(self.true_positives) / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def relevance_accuracy(self) -> float:
        return self.relevance_correct / len(self.true_positives) if self.true_positives else 0.0

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "pr": self.pr,
            "title": self.title,
            "expected": self.expected,
            "actual": self.actual,
            "true_positives": sorted(self.true_positives),
            "false_positives": sorted(self.false_positives),
            "false_negatives": sorted(self.false_negatives),
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "relevance_correct": self.relevance_correct,
            "relevance_accuracy": round(self.relevance_accuracy, 3),
        }


# ── loading ───────────────────────────────────────────────────────────────


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


def load_actual(pr: int, reports_dir: Path = REPORTS_DIR) -> dict[str, int]:
    """Read the cached agent output for this PR. Returns {risk_id: relevance}."""
    path = reports_dir / f"pr-{pr}-plan.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["id"]: r["relevance"] for r in data.get("ranked_risks", [])}


# ── scoring ───────────────────────────────────────────────────────────────


def score_case(case: dict, reports_dir: Path = REPORTS_DIR) -> CaseScore:
    expected = {r["id"]: r["relevance"] for r in case["expected_ranks"]}
    actual = load_actual(case["pr"], reports_dir)
    exp_ids = set(expected)
    act_ids = set(actual)
    tp = exp_ids & act_ids
    fp = act_ids - exp_ids
    fn = exp_ids - act_ids
    rel_correct = sum(1 for rid in tp if expected[rid] == actual[rid])
    return CaseScore(
        case_id=case["id"],
        pr=case["pr"],
        title=case["title"],
        expected=expected,
        actual=actual,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        relevance_correct=rel_correct,
    )


def aggregate(scores: list[CaseScore]) -> dict:
    tp = sum(len(s.true_positives) for s in scores)
    fp = sum(len(s.false_positives) for s in scores)
    fn = sum(len(s.false_negatives) for s in scores)
    rel = sum(s.relevance_correct for s in scores)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    rel_acc = rel / tp if tp else 0.0
    return {
        "cases": len(scores),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "relevance_correct": rel,
        "relevance_accuracy": round(rel_acc, 3),
    }


# ── refresh (optional re-run of the agent) ────────────────────────────────


def refresh_case(case: dict, reports_dir: Path, model: str) -> None:
    """Re-run the agent against the case's live PR diff and overwrite the cached report."""
    from risk_agent.render import render_markdown  # local import: render is run-only

    risks = parse_register()
    diff = fetch_pr(case["pr"], case["repo"])
    result = prioritise(risks, diff, model=model)
    md = render_markdown(result, diff)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"pr-{case['pr']}-plan.md").write_text(md, encoding="utf-8")
    (reports_dir / f"pr-{case['pr']}-plan.json").write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")


# ── markdown render ───────────────────────────────────────────────────────


def render_eval_markdown(scores: list[CaseScore], totals: dict, today: date | None = None) -> str:
    today = today or date.today()
    lines: list[str] = []
    lines.append("# risk_agent v2 v2 — golden-set evaluation")
    lines.append("")
    lines.append(f"_Run: {today.isoformat()}_")
    lines.append("")
    lines.append(
        "Compares the agent's emitted ranking (cached under `reports/pr-N-plan.json`) "
        "against the expected ranking per historic PR in [`golden_set.yaml`](../golden_set.yaml). "
        "Scoring is deterministic — no LLM in the scoring path."
    )
    lines.append("")

    lines.append("## Totals (micro-averaged)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Cases scored | {totals['cases']} |")
    lines.append(f"| True positives | {totals['true_positives']} |")
    lines.append(f"| False positives (over-pull) | {totals['false_positives']} |")
    lines.append(f"| False negatives (missed) | {totals['false_negatives']} |")
    lines.append(f"| **Precision** | **{totals['precision']:.3f}** |")
    lines.append(f"| **Recall** | **{totals['recall']:.3f}** |")
    lines.append(f"| **F1** | **{totals['f1']:.3f}** |")
    lines.append(
        f"| Relevance accuracy (matching `direct`/`plausible` on TPs) | {totals['relevance_accuracy']:.3f} "
        f"({totals['relevance_correct']}/{totals['true_positives']}) |"
    )
    lines.append("")

    lines.append("## Per-case")
    lines.append("")
    for s in scores:
        lines.append(f"### {s.case_id} — {s.title}")
        lines.append("")
        lines.append(f"**PR #{s.pr}** | precision: `{s.precision:.3f}` | recall: `{s.recall:.3f}` | F1: `{s.f1:.3f}`")
        lines.append("")
        lines.append(f"- Expected: {_fmt_set(s.expected)}")
        lines.append(f"- Actual:   {_fmt_set(s.actual)}")
        lines.append("")
        if s.true_positives:
            tps = ", ".join(
                f"{rid} (expected {s.expected[rid]}, got {s.actual[rid]})" for rid in sorted(s.true_positives)
            )
            lines.append(f"- ✓ TP: {tps}")
        if s.false_positives:
            lines.append(f"- ✗ FP (over-pull): {', '.join(sorted(s.false_positives))}")
        if s.false_negatives:
            lines.append(f"- ✗ FN (missed): {', '.join(sorted(s.false_negatives))}")
        if not (s.true_positives or s.false_positives or s.false_negatives):
            lines.append("- (no overlap and no expected/actual — empty case)")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `risk_agent.eval` (phase 9 v2 v2). Source of truth: "
        "[`golden_set.yaml`](../golden_set.yaml). Per-PR raw output: "
        "[`reports/pr-N-plan.json`](.)._"
    )
    lines.append("")
    return "\n".join(lines)


def _fmt_set(d: dict[str, int]) -> str:
    if not d:
        return "_(empty)_"
    return ", ".join(f"`{rid}({rel})`" for rid, rel in sorted(d.items()))


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    # The eval markdown uses ✓/✗ glyphs. Reconfigure stdout to UTF-8 so the
    # print() below survives Windows' cp1252 default.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="risk_agent v2 v2 — golden-set evaluation")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=GOLDEN_SET_PATH,
        help="Path to golden_set.yaml (default: risk_agent/golden_set.yaml)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Where the per-PR plan JSON files live (default: risk_agent/reports)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-run the agent against each case's PR before scoring (slow — touches Ollama).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Agent model for --refresh (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the report to stdout but do not save eval-report.{md,json}",
    )
    args = parser.parse_args(argv)

    cases = load_golden_set(args.golden_set)
    if args.refresh:
        for case in cases:
            print(f"refreshing {case['case_id']} (PR #{case['pr']})...", file=sys.stderr)
            refresh_case(case, args.reports_dir, args.model)

    scores = [score_case(c, args.reports_dir) for c in cases]
    totals = aggregate(scores)
    md = render_eval_markdown(scores, totals)
    print(md)

    if not args.no_write:
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        md_path = args.reports_dir / "eval-report.md"
        json_path = args.reports_dir / "eval-report.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(
            json.dumps({"totals": totals, "cases": [s.to_json() for s in scores]}, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote: {md_path}\n       {json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
